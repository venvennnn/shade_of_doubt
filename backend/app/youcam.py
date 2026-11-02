"""YouCam AI Skin Analysis v2.1 adapter.

File registration follows the documented flow: POST the file metadata, PUT the
bytes to the returned URL with the returned headers, then create a task with
src_file_id. The default file path is /s2s/v2.0/file, which is the path in the
current integration guide. YOUCAM_FILE_PATH overrides it.

Tasks use POST /s2s/v2.1/task/skin-analysis and GET
/s2s/v2.1/task/skin-analysis/{task_id}. format=json. pf_camera_kit is omitted
because this service does not capture through Perfect Corp camera kit.

Documented poll example is about every 10 seconds. Result URLs in zip mode are
documented as valid for about two hours, and processed results for about 24
hours. Overlays are copied immediately when JSON mask URLs are present.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from dataclasses import dataclass, field

import httpx

from app.config import SCHEMA_VERSION, HD_CONCERNS, SD_CONCERNS, Settings
from app.errors import ConfigurationError, ProviderError


def assert_youcam_configured(settings: Settings) -> None:
    missing = []
    if not settings.youcam_api_key.strip():
        missing.append("YOUCAM_API_KEY")
    if not settings.youcam_base_url.strip():
        missing.append("YOUCAM_BASE_URL")
    if missing:
        raise ConfigurationError(
            "youcam_unconfigured",
            "YouCam credentials are not configured, so no analysis task can be submitted.",
            "Set " + ", ".join(missing) + " from the YouCam API console. "
            "The API will not substitute saved or example scores.",
        )


def assert_pricing_configured(settings: Settings) -> float:
    if settings.unit_cost is None:
        raise ConfigurationError(
            "pricing_unconfigured",
            "Paid YouCam work is blocked because YOUCAM_UNIT_COST_PER_TASK is empty.",
            "Set YOUCAM_UNIT_COST_PER_TASK to the unit cost for one task at your concern count. "
            "Perfect Corp documents SD 5–8 concerns as 12 units and HD 5–8 concerns as 16 units "
            "(AI Skin Analysis unit consumption table, v2.0/v2.1). Confirm the figure on your account "
            "before setting it. This service will not assume a price.",
        )
    if settings.unit_cost <= 0:
        raise ConfigurationError(
            "pricing_invalid",
            "YOUCAM_UNIT_COST_PER_TASK must be a positive number.",
            "Set the configured per-task unit cost from your YouCam plan.",
        )
    return settings.unit_cost


def validate_concern_tier(concerns: list[str]) -> str:
    unknown = [item for item in concerns if item not in SD_CONCERNS and item not in HD_CONCERNS]
    if unknown:
        raise ConfigurationError(
            "unknown_concern",
            f"Unknown concern names: {', '.join(unknown)}.",
            "Use documented SD names (texture, pore, redness, oiliness, moisture, acne, age_spot, …) "
            "or documented HD names. Do not invent aliases.",
        )
    sd = [item for item in concerns if item in SD_CONCERNS]
    hd = [item for item in concerns if item in HD_CONCERNS]
    if sd and hd:
        raise ConfigurationError(
            "mixed_concern_tier",
            "SD and HD actions cannot be mixed in one YouCam task.",
            "Choose either the SD subset or the HD subset for the whole experiment.",
        )
    if not concerns:
        raise ConfigurationError(
            "no_concerns",
            "Select at least one documented concern.",
            "The default SD subset is texture, pore, redness, oiliness, moisture, acne, age_spot.",
        )
    return "hd" if hd else "sd"


@dataclass
class ParsedScore:
    concern: str
    region: str
    raw_score: float | None
    ui_score: int | None
    general_score: float | None
    mask_urls: list[str] = field(default_factory=list)
    raw_available: bool = False
    unavailable_reason: str | None = None


@dataclass
class ParsedTask:
    task_status: str
    error_code: str | None
    error_message: str | None
    scores: list[ParsedScore]
    schema_version: str = SCHEMA_VERSION
    http_status: int | None = None
    retry_after_seconds: float | None = None


def _as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _score_from_mapping(concern: str, region: str, payload: dict) -> ParsedScore:
    raw = _as_float(payload.get("raw_score")) if isinstance(payload, dict) else None
    ui = _as_int(payload.get("ui_score")) if isinstance(payload, dict) else None
    general = _as_float(payload.get("score")) if isinstance(payload, dict) else None
    masks = []
    if isinstance(payload, dict):
        raw_masks = payload.get("mask_urls") or []
        if isinstance(raw_masks, list):
            masks = [item for item in raw_masks if isinstance(item, str)]
    reason = None if raw is not None else "raw_score was absent; ui_score was not substituted"
    return ParsedScore(
        concern=concern,
        region=region,
        raw_score=raw,
        ui_score=ui,
        general_score=general,
        mask_urls=masks,
        raw_available=raw is not None,
        unavailable_reason=reason,
    )


def _walk_score_dict(concern: str, payload: dict, into: list[ParsedScore]) -> None:
    if not isinstance(payload, dict):
        return
    if "raw_score" in payload or "ui_score" in payload or "score" in payload:
        into.append(_score_from_mapping(concern, "", payload))
        return
    for region, child in payload.items():
        if region in {"output_mask_name", "mask_urls"}:
            continue
        if isinstance(child, dict):
            into.append(_score_from_mapping(concern, str(region), child))


def parse_task_payload(payload: dict, http_status: int | None = None) -> ParsedTask:
    if not isinstance(payload, dict):
        raise ProviderError("invalid_provider_payload", "YouCam returned a non-object payload.", "Retry the status read. Do not invent scores.")
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    status = str(data.get("task_status") or "")
    error_code = data.get("error") or data.get("error_code")
    error_message = data.get("error_message") or payload.get("error")
    results = data.get("results") if isinstance(data.get("results"), dict) else {}
    output = results.get("output")
    scores: list[ParsedScore] = []
    if isinstance(output, list):
        for entry in output:
            if not isinstance(entry, dict):
                continue
            concern = str(entry.get("type") or entry.get("concern") or "")
            if not concern or concern == "llm_results":
                continue
            region = str(entry.get("region") or "")
            scores.append(_score_from_mapping(concern, region, entry))
    elif isinstance(output, dict):
        for concern, child in output.items():
            if isinstance(child, dict):
                _walk_score_dict(str(concern), child, scores)
    elif isinstance(data.get("score_info"), dict):
        for concern, child in data["score_info"].items():
            if isinstance(child, dict):
                _walk_score_dict(str(concern), child, scores)
    if error_code is not None:
        error_code = str(error_code)
    if error_message is not None:
        error_message = str(error_message)[:500]
    return ParsedTask(
        task_status=status,
        error_code=error_code,
        error_message=error_message,
        scores=scores,
        http_status=http_status,
    )


def primary_score(scores: list[ParsedScore], concern: str) -> ParsedScore | None:
    matches = [item for item in scores if item.concern == concern]
    if not matches:
        return None
    for region in ("", "whole", "all"):
        for item in matches:
            if item.region == region:
                return item
    return ParsedScore(
        concern=concern,
        region="",
        raw_score=None,
        ui_score=None,
        general_score=None,
        raw_available=False,
        unavailable_reason="only regional scores were returned; they were stored and not averaged",
    )


def verify_webhook(secret: str, headers: dict, body: bytes, now: float | None = None) -> None:
    if not secret:
        raise ConfigurationError(
            "webhook_unconfigured",
            "YOUCAM_WEBHOOK_SECRET is empty, so unsigned callbacks are refused.",
            "Configure a Standard Webhooks secret, or leave webhooks unused and rely on polling.",
        )
    wid = headers.get("webhook-id") or headers.get("Webhook-Id")
    timestamp = headers.get("webhook-timestamp") or headers.get("Webhook-Timestamp")
    signature = headers.get("webhook-signature") or headers.get("Webhook-Signature")
    if not wid or not timestamp or not signature:
        raise ProviderError("webhook_headers_missing", "Webhook signature headers are missing.", "Refuse the delivery.")
    try:
        sent = int(timestamp)
    except ValueError as exc:
        raise ProviderError("webhook_timestamp_invalid", "Webhook timestamp is not an integer.", "") from exc
    current = time.time() if now is None else now
    if abs(current - sent) > 300:
        raise ProviderError("webhook_timestamp_stale", "Webhook timestamp is outside the 5 minute window.", "")
    token = secret[6:] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(token)
    except Exception as exc:
        raise ConfigurationError(
            "webhook_secret_invalid",
            "YOUCAM_WEBHOOK_SECRET is not valid base64 after the whsec_ prefix.",
            "Copy the secret from the YouCam webhook configuration.",
        ) from exc
    signed = f"{wid}.{timestamp}.".encode() + body
    digest = base64.b64encode(hmac.new(key, signed, hashlib.sha256).digest()).decode()
    candidates = []
    for part in signature.split():
        version, _, value = part.partition(",")
        if version == "v1" and value:
            candidates.append(value)
    if not any(hmac.compare_digest(item, digest) for item in candidates):
        raise ProviderError("webhook_signature_mismatch", "Webhook signature did not match.", "Refuse the delivery.")


class YouCamClient:
    def __init__(self, settings: Settings, http: httpx.Client | None = None):
        assert_youcam_configured(settings)
        self.settings = settings
        self.http = http or httpx.Client(timeout=httpx.Timeout(60.0, connect=20.0))
        self._owns_client = http is None

    def close(self) -> None:
        if self._owns_client:
            self.http.close()

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.settings.youcam_api_key}", "Content-Type": "application/json"}

    def register_and_upload(self, filename: str, content_type: str, data: bytes) -> str:
        url = self.settings.youcam_base_url.rstrip("/") + self.settings.youcam_file_path
        try:
            response = self.http.post(
                url,
                headers=self._headers(),
                json={"files": [{"content_type": content_type, "file_name": filename, "file_size": len(data)}]},
            )
        except httpx.TransportError as exc:
            raise ProviderError(
                "file_registration_transport",
                "YouCam file registration could not be reached.",
                "No analysis task was created by this attempt.",
                ambiguous=False,
            ) from exc
        self._raise_for_status(response, "file registration")
        body = response.json()
        files = ((body.get("data") or {}).get("files") or [])
        if not files:
            raise ProviderError("file_registration_empty", "YouCam file registration returned no file_id.", "Check YOUCAM_FILE_PATH and the API key.")
        file_id = files[0].get("file_id")
        requests = files[0].get("requests") or []
        if not file_id or not requests:
            raise ProviderError("file_registration_incomplete", "YouCam file registration did not include an upload URL.", "Check the file API response shape.")
        target = requests[0]
        put_headers = {str(key): str(value) for key, value in (target.get("headers") or {}).items()}
        put_headers.setdefault("Content-Type", content_type)
        try:
            uploaded = self.http.request(target.get("method") or "PUT", target["url"], content=data, headers=put_headers)
        except httpx.TransportError as exc:
            raise ProviderError(
                "file_upload_transport",
                "The connection dropped while uploading image bytes.",
                "No analysis task was created by this attempt.",
                ambiguous=False,
            ) from exc
        if uploaded.status_code >= 400:
            raise ProviderError(
                "file_upload_failed",
                f"Uploading bytes to YouCam storage failed with HTTP {uploaded.status_code}.",
                "The file was not submitted for analysis. No score was invented.",
            )
        return str(file_id)

    def create_task(self, file_id: str, concerns: list[str]) -> str:
        validate_concern_tier(concerns)
        url = self.settings.youcam_base_url.rstrip("/") + self.settings.youcam_task_path
        payload = {
            "src_file_id": file_id,
            "dst_actions": concerns,
            "format": "json",
            "miniserver_args": {"enable_mask_overlay": self.settings.youcam_enable_mask_overlay},
        }
        try:
            response = self.http.post(url, headers=self._headers(), json=payload)
        except httpx.TransportError as exc:
            raise ProviderError(
                "task_create_transport",
                "The connection dropped while creating a YouCam task.",
                "Do not submit a second paid task until this one is reconciled.",
                ambiguous=True,
            ) from exc
        if response.status_code >= 500:
            raise ProviderError(
                "task_create_server",
                f"YouCam task creation returned HTTP {response.status_code}.",
                "The task may have been created. Do not submit a duplicate until it is reconciled.",
                ambiguous=True,
                http_status=response.status_code,
            )
        self._raise_for_status(response, "task create")
        body = response.json()
        task_id = (body.get("data") or {}).get("task_id")
        if not task_id:
            raise ProviderError(
                "task_id_missing",
                "YouCam accepted the call but did not return a task_id. The submission is ambiguous.",
                "Do not create another paid task until this one is reconciled in the API console.",
                ambiguous=True,
            )
        return str(task_id)

    def get_task(self, task_id: str) -> ParsedTask:
        url = self.settings.youcam_base_url.rstrip("/") + self.settings.youcam_task_path.rstrip("/") + f"/{task_id}"
        try:
            response = self.http.get(url, headers={"Authorization": f"Bearer {self.settings.youcam_api_key}"})
        except httpx.TransportError:
            return ParsedTask(
                task_status="running",
                error_code="transport",
                error_message="status poll could not reach YouCam",
                scores=[],
                retry_after_seconds=self.settings.youcam_poll_interval_seconds,
            )
        retry_after = _retry_after(response)
        if response.status_code == 429 or response.status_code >= 500:
            parsed = ParsedTask(
                task_status="running",
                error_code=f"http_{response.status_code}",
                error_message="temporary provider status",
                scores=[],
                http_status=response.status_code,
                retry_after_seconds=retry_after,
            )
            return parsed
        if response.status_code >= 400:
            self._raise_for_status(response, "task status")
        parsed = parse_task_payload(response.json(), response.status_code)
        parsed.retry_after_seconds = retry_after
        return parsed

    def download(self, url: str) -> bytes:
        response = self.http.get(url, timeout=60.0)
        if response.status_code >= 400:
            raise ProviderError(
                "overlay_download_failed",
                f"Overlay download failed with HTTP {response.status_code}.",
                "The score is kept. The overlay is marked unavailable.",
            )
        return response.content

    def _raise_for_status(self, response: httpx.Response, action: str) -> None:
        if response.status_code < 400:
            return
        message = f"YouCam {action} failed with HTTP {response.status_code}."
        code = "provider_rejected"
        try:
            body = response.json()
            if isinstance(body, dict):
                message = str(body.get("error") or body.get("error_message") or message)[:500]
                code = str(body.get("error_code") or body.get("error") or code)
        except Exception:
            pass
        raise ProviderError(
            code,
            message,
            "No substitute score was created.",
            ambiguous=response.status_code >= 500,
            http_status=response.status_code,
        )


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("Retry-After")
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def safe_task_metadata(parsed: ParsedTask) -> dict:
    return {
        "schema_version": parsed.schema_version,
        "task_status": parsed.task_status,
        "error_code": parsed.error_code,
        "error_message": parsed.error_message,
        "http_status": parsed.http_status,
        "score_count": len(parsed.scores),
        "concerns_with_raw": sorted({item.concern for item in parsed.scores if item.raw_available}),
        "concerns_missing_raw": sorted({item.concern for item in parsed.scores if not item.raw_available}),
    }

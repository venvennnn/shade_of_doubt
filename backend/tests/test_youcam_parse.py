import base64
import hashlib
import hmac
import time

import httpx
import pytest

from app.config import get_settings
from app.errors import ConfigurationError, ProviderError
from app.youcam import YouCamClient, parse_task_payload, primary_score, validate_concern_tier, verify_webhook


def test_json_scores_keep_raw_and_ui_separate_and_do_not_average_regions():
    parsed = parse_task_payload(
        {
            "status": 200,
            "data": {
                "task_status": "success",
                "results": {
                    "output": [
                        {"type": "texture", "ui_score": 68, "raw_score": 57.33, "mask_urls": ["https://example.invalid/texture"]},
                        {"type": "pore", "region": "forehead", "raw_score": 10, "ui_score": 20},
                        {"type": "pore", "region": "whole", "raw_score": 40, "ui_score": 50},
                        {"type": "acne", "ui_score": 80},
                    ]
                },
            },
        }
    )
    texture = primary_score(parsed.scores, "texture")
    pore = primary_score(parsed.scores, "pore")
    acne = primary_score(parsed.scores, "acne")
    assert texture.raw_score == 57.33
    assert texture.ui_score == 68
    assert pore.region == "whole"
    assert pore.raw_score == 40
    assert acne.raw_available is False
    assert acne.raw_score is None


def test_mixed_hd_sd_is_rejected():
    with pytest.raises(ConfigurationError):
        validate_concern_tier(["texture", "hd_pore"])


def test_webhook_signature_round_trip():
    secret_bytes = b"super-secret-key"
    secret = "whsec_" + base64.b64encode(secret_bytes).decode()
    body = b'{"data":{"task_id":"abc","task_status":"success"}}'
    timestamp = str(int(time.time()))
    signed = f"msg.1.{timestamp}.".encode() + body
    digest = base64.b64encode(hmac.new(secret_bytes, signed, hashlib.sha256).digest()).decode()
    verify_webhook(secret, {"webhook-id": "msg.1", "webhook-timestamp": timestamp, "webhook-signature": f"v1,{digest}"}, body)
    with pytest.raises(ProviderError):
        verify_webhook(secret, {"webhook-id": "msg.1", "webhook-timestamp": timestamp, "webhook-signature": "v1,aaaa"}, body)


def test_missing_key_is_a_configuration_error(monkeypatch):
    settings = get_settings()
    original = settings.youcam_api_key
    settings.youcam_api_key = ""
    try:
        with pytest.raises(ConfigurationError) as caught:
            YouCamClient(settings)
        assert "YOUCAM_API_KEY" in caught.value.remediation
    finally:
        settings.youcam_api_key = original


def test_retry_after_is_parsed(monkeypatch):
    settings = get_settings()
    client = YouCamClient(settings, http=httpx.Client(transport=httpx.MockTransport(_handler)))
    parsed = client.get_task("task-1")
    assert parsed.task_status == "running"
    assert parsed.retry_after_seconds == 12


def _handler(request: httpx.Request) -> httpx.Response:
    return httpx.Response(429, headers={"Retry-After": "12"}, json={"error": "slow down"})

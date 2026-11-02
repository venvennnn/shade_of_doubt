"""Owner-scoped experiment, catalogue, consent, and deletion services."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import (
    COLOUR_CONVERSION,
    ENCODE_METHOD,
    FORMULA_ID,
    PIPELINE_VERSION,
    RESIZE_METHOD,
    Settings,
)
from app.errors import ConflictError, ForbiddenError, NotFoundError, RequestLimitError
from app.imaging import pipeline_description, render_master, sha256_bytes, validate_capture, variant_plan
from app.models import (
    Asset,
    CatalogueProduct,
    ConcernScore,
    Consent,
    Experiment,
    GuidedAsset,
    Job,
    ProductMapping,
    ProviderTask,
    RankingSnapshot,
    RateBucket,
    RecaptureSession,
    RuleVersion,
    UsageLedger,
    Variant,
    utcnow,
)
from app.quotas import reserve_units
from app.ranking import formula_document
from app.storage import Storage
from app.youcam import assert_pricing_configured, assert_youcam_configured, validate_concern_tier
from app.analysis import direction_block


def new_id() -> str:
    return str(uuid.uuid4())


def consent_text(settings: Settings) -> str:
    return (
        f"Shade of Doubt consent {settings.consent_version}. "
        "I agree that photographs I submit will be sent to Perfect Corp YouCam AI Skin Analysis for this audit. "
        f"This service keeps the photograph, derived variants, provider overlays, and scores for {settings.retention_days} days, "
        "unless I delete them sooner. Perfect Corp documents its own retention of processed results (about 24 hours) and "
        "short-lived result URLs (about 2 hours); deleting data here does not erase copies the provider still holds. "
        "Appearance scores are model outputs, not physiological measurements, diagnoses, or treatment advice. "
        "Shopping suggestions are not personalised safety or efficacy advice."
    )


def record_consent(session: Session, settings: Settings, owner_id: str, external: bool, retention: bool) -> Consent:
    if not external or not retention:
        raise ConflictError(
            "consent_required",
            "External processing and the stated retention both have to be accepted before a photograph is stored.",
            "Read the consent statement and confirm both statements.",
        )
    row = Consent(
        id=new_id(),
        owner_id=owner_id,
        version=settings.consent_version,
        external_processing=True,
        retention_acknowledged=True,
        statement_hash=hashlib.sha256(consent_text(settings).encode()).hexdigest(),
        created_at=utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def latest_consent(session: Session, settings: Settings, owner_id: str) -> Consent | None:
    return (
        session.query(Consent)
        .filter(Consent.owner_id == owner_id, Consent.version == settings.consent_version)
        .order_by(Consent.created_at.desc())
        .first()
    )


def require_consent(session: Session, settings: Settings, owner_id: str) -> Consent:
    row = latest_consent(session, settings, owner_id)
    if row is None or not row.external_processing or not row.retention_acknowledged:
        raise ConflictError(
            "consent_required",
            "A current consent record is required before photographs or paid tasks are accepted.",
            "Submit consent for external YouCam processing and the stated retention period.",
        )
    return row


def enforce_rate(session: Session, settings: Settings, owner_id: str) -> None:
    window = utcnow().replace(second=0, microsecond=0)
    row = session.get(RateBucket, (owner_id, window))
    if row is None:
        row = RateBucket(owner_id=owner_id, window_start=window, count=0)
        session.add(row)
        session.flush()
    row.count += 1
    if row.count > settings.rate_limit_per_minute:
        raise RequestLimitError(
            "rate_limited",
            "Too many requests in the current minute.",
            "Wait a minute and retry. This limit is separate from the daily unit cap.",
        )


def store_capture(session: Session, storage: Storage, settings: Settings, owner_id: str, data: bytes, filename: str) -> Asset:
    require_consent(session, settings, owner_id)
    if len(data) > settings.max_upload_bytes:
        raise ConflictError(
            "upload_too_large",
            "That file is larger than the upload limit.",
            "Export a JPEG or PNG under the configured upload size. The provider limit is 10MB.",
        )
    try:
        master, encoded = render_master(data, settings.normalize_long_side)
    except Exception as exc:
        raise ConflictError(
            "decode_failed",
            "The file could not be decoded as an image after orientation correction.",
            "Upload a JPEG or PNG photograph.",
        ) from exc
    if len(encoded) > settings.max_provider_bytes:
        raise ConflictError(
            "normalised_too_large",
            "The normalised PNG is above the documented 10MB provider limit.",
            "Use a smaller photograph. The app will not switch encoding silently.",
        )
    validation = validate_capture(master, settings)
    asset = Asset(
        id=new_id(),
        owner_id=owner_id,
        kind="capture",
        storage_path=f"{owner_id}/capture/{new_id()}.png",
        content_type="image/png",
        sha256=sha256_bytes(encoded),
        byte_size=len(encoded),
        width=master.width,
        height=master.height,
        validation_json=validation,
    )
    storage.put(asset.storage_path, encoded, "image/png")
    session.add(asset)
    session.flush()
    return asset


def _owned_asset(session: Session, owner_id: str, asset_id: str) -> Asset:
    asset = session.get(Asset, asset_id)
    if asset is None or asset.owner_id != owner_id or asset.deleted_at is not None:
        raise NotFoundError("asset_not_found", "That photograph is not in this browser session.", "")
    return asset


def list_products(session: Session, owner_id: str) -> list[dict]:
    products = session.query(CatalogueProduct).filter_by(owner_id=owner_id).order_by(CatalogueProduct.created_at.desc()).all()
    return [_product_payload(session, product) for product in products]


def _product_payload(session: Session, product: CatalogueProduct) -> dict:
    mappings = session.query(ProductMapping).filter_by(product_id=product.id).all()
    return {
        "id": product.id,
        "name": product.name,
        "source_url": product.source_url,
        "image_rights": product.image_rights,
        "price": product.price,
        "currency": product.currency,
        "ingredient_label": product.ingredient_label,
        "source_observed_at": product.source_observed_at.isoformat(),
        "image_asset_id": product.image_asset_id,
        "confirmed": product.confirmed,
        "mappings": [
            {
                "id": item.id,
                "concern": item.concern,
                "support_note": item.support_note,
                "source_url": item.source_url,
                "reviewer_confirmed": item.reviewer_confirmed,
                "mapping_version": item.mapping_version,
            }
            for item in mappings
        ],
    }


def create_product(session: Session, settings: Settings, owner_id: str, payload: dict, image: tuple[bytes, str] | None, storage: Storage) -> dict:
    require_consent(session, settings, owner_id)
    name = (payload.get("name") or "").strip()
    source_url = (payload.get("source_url") or "").strip()
    rights = (payload.get("image_rights") or "").strip()
    if not name or not source_url.startswith(("http://", "https://")) or not rights:
        raise ConflictError(
            "product_incomplete",
            "A product needs a real name, an http(s) source URL, and an image-rights statement.",
            "Enter the packaging or catalogue source you actually consulted. Do not invent a product.",
        )
    observed = payload.get("source_observed_at")
    try:
        observed_at = datetime.fromisoformat(observed)
    except Exception as exc:
        raise ConflictError(
            "source_timestamp_required",
            "source_observed_at must be an ISO timestamp for when you read the source.",
            "Record when you checked the product page or packaging.",
        ) from exc
    image_asset_id = None
    if image is not None:
        data, _filename = image
        stored = store_capture(session, storage, settings, owner_id, data, "packshot")
        stored.kind = "product"
        image_asset_id = stored.id
    product = CatalogueProduct(
        id=new_id(),
        owner_id=owner_id,
        name=name,
        source_url=source_url,
        image_rights=rights,
        price=(str(payload["price"]) if payload.get("price") not in (None, "") else None),
        currency=(payload.get("currency") or None),
        ingredient_label=payload.get("ingredient_label") or None,
        source_observed_at=observed_at,
        image_asset_id=image_asset_id,
        confirmed=bool(payload.get("confirmed")),
    )
    session.add(product)
    for item in payload.get("mappings") or []:
        concern = (item.get("concern") or "").strip()
        note = (item.get("support_note") or "").strip()
        map_url = (item.get("source_url") or source_url).strip()
        if not concern or not note:
            raise ConflictError(
                "mapping_incomplete",
                "Each concern mapping needs the concern name and a support note citing the source.",
                "Unconfirmed or empty mappings are not guessed.",
            )
        validate_concern_tier([concern])
        session.add(
            ProductMapping(
                id=new_id(),
                product_id=product.id,
                owner_id=owner_id,
                concern=concern,
                support_note=note,
                source_url=map_url,
                reviewer_confirmed=bool(item.get("reviewer_confirmed")),
            )
        )
    session.flush()
    return _product_payload(session, product)


def confirm_product(session: Session, owner_id: str, product_id: str, confirmed: bool) -> dict:
    product = session.get(CatalogueProduct, product_id)
    if product is None or product.owner_id != owner_id:
        raise NotFoundError("product_not_found", "That product is not in this browser session.", "")
    product.confirmed = confirmed
    session.flush()
    return _product_payload(session, product)


def _catalogue_snapshot(session: Session, owner_id: str, product_ids: list[str]) -> list[dict]:
    if not product_ids:
        return []
    products = session.query(CatalogueProduct).filter(CatalogueProduct.owner_id == owner_id, CatalogueProduct.id.in_(product_ids)).all()
    found = {product.id: product for product in products}
    missing = [item for item in product_ids if item not in found]
    if missing:
        raise NotFoundError("product_not_found", "A selected product is not in this browser session.", "")
    snapshot = []
    for product_id in product_ids:
        product = found[product_id]
        if not product.confirmed:
            raise ConflictError(
                "product_unconfirmed",
                f"{product.name} is not confirmed.",
                "Confirm the catalogue entry before including it in an audit.",
            )
        payload = _product_payload(session, product)
        payload["mappings"] = [item for item in payload["mappings"] if item["reviewer_confirmed"]]
        snapshot.append(payload)
    return snapshot


def _ensure_rule(session: Session, settings: Settings, owner_id: str, top_k: int) -> RuleVersion:
    document = formula_document(settings.score_direction, top_k)
    latest = (
        session.query(RuleVersion).filter_by(owner_id=owner_id, formula_id=FORMULA_ID).order_by(RuleVersion.created_at.desc()).first()
    )
    if latest and latest.formula_json == document and latest.score_direction == settings.score_direction:
        return latest
    row = RuleVersion(
        id=new_id(),
        owner_id=owner_id,
        formula_id=FORMULA_ID,
        formula_json=document,
        score_direction=settings.score_direction,
    )
    session.add(row)
    session.flush()
    return row


def build_plan(settings: Settings, concerns: list[str], factors: list[str], product_count: int, top_k: int) -> dict:
    assert_youcam_configured(settings)
    cost = assert_pricing_configured(settings)
    tier = validate_concern_tier(concerns)
    _check_factors(factors)
    plan = variant_plan(settings, factors)
    tasks = 1 + len(plan)
    return {
        "pipeline": pipeline_description(settings),
        "tier": tier,
        "concerns": concerns,
        "tasks": [{"role": "baseline", "key": "baseline", "factor": "none", "params": {"encoding": ENCODE_METHOD}}] + plan,
        "task_count": tasks,
        "unit_cost_per_task": cost,
        "estimated_units": cost * tasks,
        "pricing": "configured_estimate",
        "charge_note": (
            "This estimate multiplies the configured per-task cost by the planned submissions. "
            "Perfect Corp documents that units are consumed on success and not on engine error. "
            "The task status payload used here does not include a per-task charge, so units_confirmed stays empty "
            "and successful tasks remain estimated."
        ),
        "product_count": product_count,
        "score_only": product_count == 0,
        "minimum_valid_variants": settings.min_valid_variants,
        "score_direction": direction_block(settings.score_direction),
        "formula": formula_document(settings.score_direction, top_k),
        "fresh_call": "Every run submits a new baseline and new variants. Saved charts are not reused.",
    }


def _check_factors(factors: list[str]) -> None:
    allowed = {"exposure", "colour_balance", "framing"}
    if not factors or any(item not in allowed for item in factors):
        raise ConflictError(
            "factors_invalid",
            "Choose one or more of exposure, colour_balance, and framing.",
            "The default experiment uses all three, one change at a time.",
        )


def create_experiment(
    session: Session,
    storage: Storage,
    settings: Settings,
    owner_id: str,
    body: dict,
    idempotency_key: str | None,
) -> tuple[Experiment, bool]:
    require_consent(session, settings, owner_id)
    concerns = body.get("concerns") or settings.default_concerns
    factors = body.get("factors") or ["exposure", "colour_balance", "framing"]
    top_k = int(body.get("top_k") or settings.default_top_k)
    product_ids = list(body.get("product_ids") or [])
    priorities = {concern: float((body.get("priorities") or {}).get(concern, 1)) for concern in concerns}
    if any(value < 0 for value in priorities.values()):
        raise ConflictError("priority_invalid", "Concern priorities cannot be negative.", "")
    catalogue = _catalogue_snapshot(session, owner_id, product_ids)
    plan_body = build_plan(settings, concerns, factors, len(catalogue), top_k)
    request_hash = hashlib.sha256(json.dumps(body, sort_keys=True, default=str).encode()).hexdigest()
    if idempotency_key:
        existing = session.query(Experiment).filter_by(owner_id=owner_id, idempotency_key=idempotency_key).one_or_none()
        if existing is not None:
            if existing.request_hash != request_hash:
                raise ConflictError(
                    "idempotency_conflict",
                    "That idempotency key was already used for a different request.",
                    "Use a new key, or retry the original request body.",
                )
            return existing, False
    guided = body.get("guided_asset_id")
    if guided:
        asset = _copy_guided(session, storage, settings, owner_id, guided)
    else:
        asset = _owned_asset(session, owner_id, body.get("asset_id") or "")
    if not (asset.validation_json or {}).get("ok"):
        raise ConflictError(
            "capture_not_accepted",
            "The photograph did not pass the local capture checks.",
            "Retake the photograph. These checks are local heuristics, and a provider call is not started.",
        )
    rule = _ensure_rule(session, settings, owner_id, top_k)
    experiment_id = new_id()
    reserve_units(session, settings, owner_id, experiment_id, plan_body["task_count"])
    config = {
        "concerns": concerns,
        "factors": factors,
        "plan": plan_body["tasks"][1:],
        "pipeline": plan_body["pipeline"],
        "priorities": priorities,
        "excluded_product_ids": list(body.get("excluded_product_ids") or []),
        "excluded_ingredients": list(body.get("excluded_ingredients") or []),
        "top_k": top_k,
        "minimum_valid_variants": settings.min_valid_variants,
        "score_direction": settings.score_direction,
        "catalogue": {"products": catalogue},
        "guided": bool(guided),
        "unit_cost_per_task": plan_body["unit_cost_per_task"],
        "estimated_units": plan_body["estimated_units"],
        "provider": {
            "base_url": settings.youcam_base_url,
            "task_path": settings.youcam_task_path,
            "file_path": settings.youcam_file_path,
            "format": "json",
        },
    }
    experiment = Experiment(
        id=experiment_id,
        owner_id=owner_id,
        asset_id=asset.id,
        status="running",
        stage="queued",
        config_json=config,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        rule_version_id=rule.id,
    )
    session.add(experiment)
    session.add(_variant_row(owner_id, experiment_id, "baseline", "baseline", "none", {"encoding": ENCODE_METHOD}, 0))
    for index, spec in enumerate(config["plan"], start=1):
        session.add(_variant_row(owner_id, experiment_id, "variant", spec["key"], spec["factor"], spec["params"], index))
    session.add(
        Job(
            id=new_id(),
            owner_id=owner_id,
            experiment_id=experiment_id,
            kind="experiment",
            status="queued",
            payload_json={"experiment_id": experiment_id},
            max_attempts=settings.worker_max_attempts,
            run_after=utcnow(),
        )
    )
    session.flush()
    return experiment, True


def _variant_row(owner_id: str, experiment_id: str, role: str, key: str, factor: str, params: dict, order: int) -> Variant:
    return Variant(
        id=new_id(),
        experiment_id=experiment_id,
        owner_id=owner_id,
        role=role,
        key=key,
        factor=factor,
        status="pending",
        params_json=params,
        pipeline_version=PIPELINE_VERSION,
        colour_conversion=COLOUR_CONVERSION,
        resize_method=RESIZE_METHOD,
        encode_method=ENCODE_METHOD,
        sort_order=order,
        unit_state="reserved",
    )


def _copy_guided(session: Session, storage: Storage, settings: Settings, owner_id: str, guided_id: str) -> Asset:
    guided = session.get(GuidedAsset, guided_id)
    if guided is None or not guided.published:
        raise NotFoundError(
            "guided_asset_unavailable",
            "No published, rights-cleared guided photograph is available with that id.",
            "Upload your own photograph. Guided mode does not invent a sample.",
        )
    source = session.get(Asset, guided.asset_id)
    data = storage.get(source.storage_path)
    copied = store_capture(session, storage, settings, owner_id, data, "guided.png")
    copied.kind = "guided_copy"
    copied.validation_json = {
        **(copied.validation_json or {}),
        "guided_asset_id": guided.id,
        "rights_statement": guided.rights_statement,
        "consent_statement": guided.consent_statement,
    }
    session.flush()
    return copied


def add_recapture(session: Session, storage: Storage, settings: Settings, owner_id: str, experiment_id: str, data: bytes, condition: str, note: str) -> RecaptureSession:
    experiment = owned_experiment(session, owner_id, experiment_id)
    if condition not in {"same_condition", "changed_condition"}:
        raise ConflictError(
            "condition_invalid",
            "Label the recapture as same_condition or changed_condition.",
            "Do not pool recaptures without that label.",
        )
    if experiment.status not in {"completed", "baseline_rejected", "failed", "needs_reconciliation"}:
        raise ConflictError(
            "experiment_still_running",
            "Wait until the original run finishes before adding a recapture.",
            "The recapture is a separate live task.",
        )
    asset = store_capture(session, storage, settings, owner_id, data, "recapture")
    asset.kind = "recapture"
    if not (asset.validation_json or {}).get("ok"):
        raise ConflictError(
            "capture_not_accepted",
            "The recapture did not pass the local capture checks.",
            "Take another photograph. No provider task was reserved.",
        )
    assert_youcam_configured(settings)
    reserve_units(session, settings, owner_id, experiment.id, 1)
    recapture = RecaptureSession(
        id=new_id(),
        owner_id=owner_id,
        experiment_id=experiment.id,
        condition=condition,
        note=note or "",
        asset_id=asset.id,
        status="queued",
    )
    session.add(recapture)
    session.add(
        Job(
            id=new_id(),
            owner_id=owner_id,
            experiment_id=experiment.id,
            kind="recapture",
            status="queued",
            payload_json={"recapture_session_id": recapture.id},
            max_attempts=settings.worker_max_attempts,
            run_after=utcnow(),
        )
    )
    session.flush()
    return recapture


def owned_experiment(session: Session, owner_id: str, experiment_id: str) -> Experiment:
    experiment = session.get(Experiment, experiment_id)
    if experiment is None or experiment.owner_id != owner_id:
        raise NotFoundError("experiment_not_found", "That audit is not in this browser session.", "")
    return experiment


def reconcile_variant(session: Session, settings: Settings, owner_id: str, experiment_id: str, body: dict) -> Experiment:
    experiment = owned_experiment(session, owner_id, experiment_id)
    variant = session.get(Variant, body.get("variant_id"))
    if variant is None or variant.owner_id != owner_id or variant.experiment_id != experiment.id:
        raise NotFoundError("variant_not_found", "That variant is not in this audit.", "")
    task = session.query(ProviderTask).filter_by(variant_id=variant.id).one_or_none()
    if task is None or task.status != "needs_reconciliation":
        raise ConflictError(
            "not_ambiguous",
            "That variant is not waiting for reconciliation.",
            "Only an ambiguous submission can be attached or cleared.",
        )
    resolution = body.get("resolution")
    if resolution == "attach_task":
        provider_id = (body.get("provider_task_id") or "").strip()
        if not provider_id:
            raise ConflictError("task_id_required", "Paste the task id from the YouCam console.", "")
        task.provider_task_id = provider_id
        task.status = "running"
        variant.status = "running"
        task.error_code = None
        task.error_message = None
    elif resolution == "not_created":
        session.delete(task)
        variant.status = "generated"
        variant.rejection_reason = None
    else:
        raise ConflictError(
            "resolution_invalid",
            "Use attach_task or not_created.",
            "Check the YouCam console before allowing another submission.",
        )
    experiment.status = "running"
    experiment.stage = "queued"
    experiment.error_message = None
    session.add(
        Job(
            id=new_id(),
            owner_id=owner_id,
            experiment_id=experiment.id,
            kind="experiment",
            status="queued",
            payload_json={"experiment_id": experiment.id, "reconciled": True},
            max_attempts=settings.worker_max_attempts,
            run_after=utcnow(),
        )
    )
    session.flush()
    return experiment


def delete_experiment(session: Session, storage: Storage, owner_id: str, experiment_id: str) -> None:
    experiment = owned_experiment(session, owner_id, experiment_id)
    _destroy_experiment(session, storage, experiment)


def _destroy_experiment(session: Session, storage: Storage, experiment: Experiment) -> None:
    asset_ids = {experiment.asset_id}
    for variant in session.query(Variant).filter_by(experiment_id=experiment.id):
        if variant.asset_id:
            asset_ids.add(variant.asset_id)
    for score in session.query(ConcernScore).filter_by(experiment_id=experiment.id):
        if score.overlay_asset_id:
            asset_ids.add(score.overlay_asset_id)
    for recapture in session.query(RecaptureSession).filter_by(experiment_id=experiment.id):
        asset_ids.add(recapture.asset_id)
        session.delete(recapture)
    session.query(ConcernScore).filter_by(experiment_id=experiment.id).delete()
    session.query(ProviderTask).filter_by(experiment_id=experiment.id).delete()
    session.query(RankingSnapshot).filter_by(experiment_id=experiment.id).delete()
    session.query(Job).filter_by(experiment_id=experiment.id).delete()
    session.query(Variant).filter_by(experiment_id=experiment.id).delete()
    for row in session.query(UsageLedger).filter_by(experiment_id=experiment.id):
        row.experiment_id = None
        row.note = (row.note + " experiment deleted").strip()
    session.delete(experiment)
    session.flush()
    for asset_id in asset_ids:
        if not asset_id:
            continue
        still = session.query(Experiment).filter_by(asset_id=asset_id).count()
        guided = session.query(GuidedAsset).filter_by(asset_id=asset_id).count()
        if still or guided:
            continue
        asset = session.get(Asset, asset_id)
        if asset is None:
            continue
        try:
            storage.delete(asset.storage_path)
        except Exception:
            pass
        session.delete(asset)
    session.flush()


def delete_account(session: Session, storage: Storage, owner_id: str) -> None:
    for experiment in session.query(Experiment).filter_by(owner_id=owner_id).all():
        _destroy_experiment(session, storage, experiment)
    for product in session.query(CatalogueProduct).filter_by(owner_id=owner_id).all():
        session.query(ProductMapping).filter_by(product_id=product.id).delete()
        session.delete(product)
    for guided in session.query(GuidedAsset).filter_by(owner_id=owner_id).all():
        session.delete(guided)
    for asset in session.query(Asset).filter_by(owner_id=owner_id).all():
        try:
            storage.delete(asset.storage_path)
        except Exception:
            pass
        session.delete(asset)
    session.query(Consent).filter_by(owner_id=owner_id).delete()
    session.query(RuleVersion).filter_by(owner_id=owner_id).delete()
    session.query(UsageLedger).filter_by(owner_id=owner_id).delete()
    session.query(RateBucket).filter_by(owner_id=owner_id).delete()
    session.query(Job).filter_by(owner_id=owner_id).delete()
    session.flush()


def publish_guided(session: Session, settings: Settings, owner_id: str, asset_id: str, title: str, rights: str, consent: str) -> GuidedAsset:
    if owner_id not in settings.operators:
        raise ForbiddenError(
            "operator_only",
            "Only a configured operator session can publish a guided photograph.",
            "Set OPERATOR_USER_IDS to the owner id from GET /v1/me. With none published, the app requires an upload.",
        )
    if not title.strip() or not rights.strip() or not consent.strip():
        raise ConflictError(
            "guided_metadata_required",
            "A guided photograph needs a title, a rights statement, and a consent statement.",
            "Do not publish a photograph without rights and consent.",
        )
    asset = _owned_asset(session, owner_id, asset_id)
    if not (asset.validation_json or {}).get("ok"):
        raise ConflictError("capture_not_accepted", "The guided photograph did not pass local capture checks.", "")
    row = GuidedAsset(
        id=new_id(),
        owner_id=owner_id,
        asset_id=asset.id,
        title=title.strip(),
        rights_statement=rights.strip(),
        consent_statement=consent.strip(),
        published=True,
    )
    session.add(row)
    session.flush()
    return row


def list_guided(session: Session) -> list[dict]:
    rows = session.query(GuidedAsset).filter_by(published=True).order_by(GuidedAsset.created_at.desc()).all()
    return [
        {
            "id": row.id,
            "title": row.title,
            "rights_statement": row.rights_statement,
            "consent_statement": row.consent_statement,
        }
        for row in rows
    ]


def purge_expired(session: Session, storage: Storage, settings: Settings) -> int:
    from datetime import timedelta

    cutoff = utcnow() - timedelta(days=settings.retention_days)
    rows = (
        session.query(Experiment)
        .filter(Experiment.created_at < cutoff, Experiment.status.in_(["completed", "failed", "baseline_rejected", "needs_reconciliation"]))
        .all()
    )
    for experiment in rows:
        _destroy_experiment(session, storage, experiment)
    return len(rows)

import json
from datetime import timedelta

from fastapi import Depends, FastAPI, File, Form, Header, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analysis import direction_block
from app.auth import Principal, decode_supabase_jwt
from app.config import PIPELINE_VERSION, get_settings
from app.db import get_db
from app.errors import AppError, AuthError, ConfigurationError
from app.imaging import pipeline_description
from app.models import Experiment, Job, ProviderTask, WorkerHeartbeat, ensure_utc, utcnow
from app.runner import assemble_experiment
from app.services import (
    add_recapture,
    confirm_product,
    consent_text,
    create_experiment,
    create_product,
    delete_account,
    delete_experiment,
    enforce_rate,
    latest_consent,
    list_guided,
    list_products,
    owned_experiment,
    publish_guided,
    reconcile_variant,
    record_consent,
    store_capture,
    build_plan,
    _owned_asset,
)
from app.storage import build_storage
from app.youcam import assert_pricing_configured, assert_youcam_configured, verify_webhook

settings = get_settings()
app = FastAPI(title="Shade of Doubt", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.frontend_origin.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(AppError)
def app_error(_request: Request, exc: AppError):
    return JSONResponse(status_code=exc.status_code, content=exc.as_dict())


def get_principal(authorization: str | None = Header(default=None)) -> Principal:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise AuthError("missing_token", "Sign in is required.", "Send the Supabase access token as a bearer token.")
    return decode_supabase_jwt(authorization.split(" ", 1)[1].strip(), settings)


def _guard(session: Session, principal: Principal) -> None:
    enforce_rate(session, settings, principal.user_id)


@app.get("/health")
def health():
    return {"status": "ok", "service": "shade-of-doubt"}


@app.get("/ready")
def ready(session: Session = Depends(get_db)):
    session.execute(text("SELECT 1"))
    heartbeat = session.query(WorkerHeartbeat).order_by(WorkerHeartbeat.last_seen.desc()).first()
    worker = None
    if heartbeat is not None:
        age = (utcnow() - ensure_utc(heartbeat.last_seen)).total_seconds()
        worker = {"worker_id": heartbeat.worker_id, "age_seconds": age, "fresh": age < settings.worker_lease_seconds * 2}
    return {"status": "ready", "database": "ok", "worker": worker}


@app.get("/v1/runtime")
def runtime():
    pricing = None
    pricing_error = None
    try:
        pricing = assert_pricing_configured(settings)
    except ConfigurationError as exc:
        pricing_error = exc.as_dict()["error"]
    youcam_ready = bool(settings.youcam_api_key.strip())
    return {
        "app": "Shade of Doubt",
        "pipeline_version": PIPELINE_VERSION,
        "pipeline": pipeline_description(settings),
        "concerns": settings.default_concerns,
        "score_direction": direction_block(settings.score_direction),
        "consent_version": settings.consent_version,
        "consent_text": consent_text(settings),
        "retention_days": settings.retention_days,
        "youcam_configured": youcam_ready,
        "pricing_configured": pricing is not None,
        "unit_cost_per_task": pricing,
        "pricing_error": pricing_error,
        "user_daily_unit_cap": settings.youcam_user_daily_unit_cap,
        "global_daily_unit_cap": settings.youcam_global_daily_unit_cap,
        "minimum_valid_variants": settings.min_valid_variants,
        "storage_backend": settings.resolved_storage_backend or None,
        "auth_configured": bool(settings.supabase_url or settings.supabase_jwt_secret),
        "guided_available": True,
    }


@app.post("/v1/consents")
def post_consent(body: dict, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    row = record_consent(session, settings, principal.user_id, bool(body.get("external_processing")), bool(body.get("retention_acknowledged")))
    session.commit()
    return {"id": row.id, "version": row.version, "statement_hash": row.statement_hash}


@app.get("/v1/me")
def me(principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    consent = latest_consent(session, settings, principal.user_id)
    return {
        "user_id": principal.user_id,
        "email": principal.email,
        "consent": None
        if consent is None
        else {"version": consent.version, "accepted_at": consent.created_at.isoformat()},
    }


@app.post("/v1/assets")
async def post_asset(
    file: UploadFile = File(...),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
):
    _guard(session, principal)
    data = await file.read()
    asset = store_capture(session, build_storage(settings), settings, principal.user_id, data, file.filename or "capture")
    session.commit()
    return _asset_body(asset)


@app.get("/v1/assets/{asset_id}")
def get_asset(asset_id: str, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    asset = _owned_asset(session, principal.user_id, asset_id)
    return _asset_body(asset)


@app.get("/v1/assets/{asset_id}/content")
def get_asset_content(asset_id: str, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    asset = _owned_asset(session, principal.user_id, asset_id)
    data = build_storage(settings).get(asset.storage_path)
    return Response(content=data, media_type=asset.content_type)


@app.post("/v1/experiments/plan")
def post_plan(body: dict, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    concerns = body.get("concerns") or settings.default_concerns
    factors = body.get("factors") or ["exposure", "colour_balance", "framing"]
    top_k = int(body.get("top_k") or settings.default_top_k)
    plan = build_plan(settings, concerns, factors, len(body.get("product_ids") or []), top_k)
    return plan


@app.post("/v1/experiments", status_code=202)
def post_experiment(
    body: dict,
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
):
    _guard(session, principal)
    experiment, created = create_experiment(session, build_storage(settings), settings, principal.user_id, body, idempotency_key)
    session.commit()
    job = session.query(Job).filter_by(experiment_id=experiment.id, kind="experiment").order_by(Job.created_at.desc()).first()
    return JSONResponse(
        status_code=202,
        content={
            "experiment_id": experiment.id,
            "job_id": None if job is None else job.id,
            "status": experiment.status,
            "stage": experiment.stage,
            "created": created,
            "estimated_units": experiment.config_json.get("estimated_units"),
        },
    )


@app.get("/v1/experiments")
def get_experiments(principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    rows = session.query(Experiment).filter_by(owner_id=principal.user_id).order_by(Experiment.created_at.desc()).all()
    return {
        "experiments": [
            {
                "id": row.id,
                "status": row.status,
                "stage": row.stage,
                "created_at": row.created_at.isoformat(),
                "completed_at": row.completed_at.isoformat() if row.completed_at else None,
                "summary": row.summary_json,
                "concerns": row.config_json.get("concerns"),
            }
            for row in rows
        ]
    }


@app.get("/v1/experiments/{experiment_id}")
def get_experiment(experiment_id: str, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    experiment = owned_experiment(session, principal.user_id, experiment_id)
    return assemble_experiment(session, experiment)


@app.get("/v1/experiments/{experiment_id}/report")
def get_report(experiment_id: str, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    experiment = owned_experiment(session, principal.user_id, experiment_id)
    report = assemble_experiment(session, experiment)
    report["report_notice"] = (
        "This export lists persisted model outputs and the frozen shopping rule. "
        "It is not a diagnosis, a treatment plan, a safety certificate, or evidence of product efficacy."
    )
    return report


@app.post("/v1/experiments/{experiment_id}/recaptures", status_code=202)
async def post_recapture(
    experiment_id: str,
    file: UploadFile = File(...),
    condition: str = Form(...),
    note: str = Form(""),
    principal: Principal = Depends(get_principal),
    session: Session = Depends(get_db),
):
    _guard(session, principal)
    data = await file.read()
    recapture = add_recapture(session, build_storage(settings), settings, principal.user_id, experiment_id, data, condition, note)
    session.commit()
    return {"recapture_id": recapture.id, "status": recapture.status}


@app.post("/v1/experiments/{experiment_id}/reconcile")
def post_reconcile(experiment_id: str, body: dict, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    experiment = reconcile_variant(session, settings, principal.user_id, experiment_id, body)
    session.commit()
    return {"experiment_id": experiment.id, "status": experiment.status, "stage": experiment.stage}


@app.delete("/v1/experiments/{experiment_id}")
def remove_experiment(experiment_id: str, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    delete_experiment(session, build_storage(settings), principal.user_id, experiment_id)
    session.commit()
    return {"deleted": experiment_id}


@app.get("/v1/products")
def get_products(principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    return {"products": list_products(session, principal.user_id)}


@app.post("/v1/products")
def post_product(body: dict, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    payload = create_product(session, settings, principal.user_id, body, None, build_storage(settings))
    session.commit()
    return payload


@app.post("/v1/products/{product_id}/confirm")
def post_confirm(product_id: str, body: dict, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    payload = confirm_product(session, principal.user_id, product_id, bool(body.get("confirmed")))
    session.commit()
    return payload


@app.get("/v1/guided-assets")
def get_guided(principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    return {"guided_assets": list_guided(session)}


@app.post("/v1/guided-assets")
def post_guided(body: dict, principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    row = publish_guided(
        session,
        settings,
        principal.user_id,
        body.get("asset_id") or "",
        body.get("title") or "",
        body.get("rights_statement") or "",
        body.get("consent_statement") or "",
    )
    session.commit()
    return {"id": row.id, "title": row.title, "published": row.published}


@app.delete("/v1/account")
def remove_account(principal: Principal = Depends(get_principal), session: Session = Depends(get_db)):
    _guard(session, principal)
    delete_account(session, build_storage(settings), principal.user_id)
    session.commit()
    return {"deleted": True}


@app.post("/v1/webhooks/youcam")
async def youcam_webhook(request: Request, session: Session = Depends(get_db)):
    body = await request.body()
    verify_webhook(settings.youcam_webhook_secret, dict(request.headers), body)
    payload = json.loads(body.decode() or "{}")
    data = payload.get("data") if isinstance(payload, dict) else None
    task_id = None if not isinstance(data, dict) else data.get("task_id")
    status = None if not isinstance(data, dict) else data.get("task_status")
    if task_id:
        row = session.query(ProviderTask).filter_by(provider_task_id=str(task_id)).one_or_none()
        if row is not None:
            row.webhook_status = str(status or "")
            job = (
                session.query(Job)
                .filter(Job.experiment_id == row.experiment_id, Job.status == "queued")
                .order_by(Job.created_at.desc())
                .first()
            )
            if job is not None:
                job.run_after = utcnow()
            elif row.status in {"running", "submitting"}:
                session.add(
                    Job(
                        id=__import__("uuid").uuid4().__str__(),
                        owner_id=row.owner_id,
                        experiment_id=row.experiment_id,
                        kind="experiment",
                        status="queued",
                        payload_json={"experiment_id": row.experiment_id, "webhook": True},
                        max_attempts=settings.worker_max_attempts,
                        run_after=utcnow(),
                    )
                )
            session.commit()
    return Response(status_code=204)


def _asset_body(asset) -> dict:
    return {
        "id": asset.id,
        "kind": asset.kind,
        "sha256": asset.sha256,
        "byte_size": asset.byte_size,
        "width": asset.width,
        "height": asset.height,
        "content_type": asset.content_type,
        "validation": asset.validation_json,
        "created_at": asset.created_at.isoformat(),
    }

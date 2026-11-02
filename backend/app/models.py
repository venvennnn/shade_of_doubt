from datetime import datetime, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def ensure_utc(moment: datetime | None) -> datetime | None:
    if moment is None:
        return None
    if moment.tzinfo is None:
        return moment.replace(tzinfo=timezone.utc)
    return moment


class Consent(Base):
    __tablename__ = "consents"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    version: Mapped[str] = mapped_column(String(40))
    external_processing: Mapped[bool] = mapped_column(Boolean)
    retention_acknowledged: Mapped[bool] = mapped_column(Boolean)
    statement_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    kind: Mapped[str] = mapped_column(String(32))
    storage_path: Mapped[str] = mapped_column(String(500))
    content_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    byte_size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    validation_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Experiment(Base):
    __tablename__ = "experiments"
    __table_args__ = (UniqueConstraint("owner_id", "idempotency_key", name="uq_experiment_idempotency"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    asset_id: Mapped[str] = mapped_column(ForeignKey("assets.id"))
    status: Mapped[str] = mapped_column(String(40), index=True)
    stage: Mapped[str] = mapped_column(String(40))
    config_json: Mapped[dict] = mapped_column(JSON)
    summary_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    request_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    rule_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class Variant(Base):
    __tablename__ = "variants"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(20))
    key: Mapped[str] = mapped_column(String(40))
    factor: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(40), index=True)
    params_json: Mapped[dict] = mapped_column(JSON)
    pipeline_version: Mapped[str] = mapped_column(String(40))
    colour_conversion: Mapped[str] = mapped_column(String(80))
    resize_method: Mapped[str] = mapped_column(String(40))
    encode_method: Mapped[str] = mapped_column(String(40))
    crop_bounds_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    clipping_fraction: Mapped[float | None] = mapped_column(Float, nullable=True)
    sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    unit_state: Mapped[str] = mapped_column(String(20), default="reserved")


class Job(Base):
    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(20), index=True)
    payload_json: Mapped[dict] = mapped_column(JSON)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    lease_owner: Mapped[str | None] = mapped_column(String(80), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    heartbeat_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    run_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProviderTask(Base):
    __tablename__ = "provider_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    variant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    recapture_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, unique=True)
    provider_task_id: Mapped[str | None] = mapped_column(String(200), nullable=True, index=True)
    file_id: Mapped[str | None] = mapped_column(String(300), nullable=True)
    status: Mapped[str] = mapped_column(String(40), index=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(40), nullable=True)
    safe_metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    poll_count: Mapped[int] = mapped_column(Integer, default=0)
    submit_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    webhook_status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)


class ConcernScore(Base):
    __tablename__ = "concern_scores"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    experiment_id: Mapped[str] = mapped_column(String(36), index=True)
    variant_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    recapture_session_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    provider_task_id: Mapped[str] = mapped_column(String(36))
    concern: Mapped[str] = mapped_column(String(40))
    region: Mapped[str] = mapped_column(String(40), default="")
    raw_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    ui_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    general_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    raw_available: Mapped[bool] = mapped_column(Boolean, default=False)
    unavailable_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    overlay_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False)


class CatalogueProduct(Base):
    __tablename__ = "catalogue_products"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(Text)
    image_rights: Mapped[str] = mapped_column(Text)
    price: Mapped[str | None] = mapped_column(String(32), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(8), nullable=True)
    ingredient_label: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    image_asset_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ProductMapping(Base):
    __tablename__ = "product_mappings"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    product_id: Mapped[str] = mapped_column(ForeignKey("catalogue_products.id"), index=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    concern: Mapped[str] = mapped_column(String(40))
    support_note: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str] = mapped_column(Text)
    reviewer_confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    mapping_version: Mapped[str] = mapped_column(String(20), default="map-v1")


class RuleVersion(Base):
    __tablename__ = "rule_versions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    formula_id: Mapped[str] = mapped_column(String(80))
    formula_json: Mapped[dict] = mapped_column(JSON)
    score_direction: Mapped[str] = mapped_column(String(40))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RankingSnapshot(Base):
    __tablename__ = "ranking_snapshots"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(String(36), unique=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    rule_version_id: Mapped[str] = mapped_column(String(36))
    catalogue_json: Mapped[dict] = mapped_column(JSON)
    result_json: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RecaptureSession(Base):
    __tablename__ = "recapture_sessions"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    condition: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(Text, default="")
    asset_id: Mapped[str] = mapped_column(String(36))
    status: Mapped[str] = mapped_column(String(40), default="queued")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class UsageLedger(Base):
    __tablename__ = "usage_ledger"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    experiment_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    day: Mapped[datetime] = mapped_column(Date, index=True)
    kind: Mapped[str] = mapped_column(String(20))
    units_estimated: Mapped[float] = mapped_column(Float)
    units_confirmed: Mapped[float | None] = mapped_column(Float, nullable=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class RateBucket(Base):
    __tablename__ = "rate_buckets"

    owner_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), primary_key=True)
    count: Mapped[int] = mapped_column(Integer, default=0)


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeats"

    worker_id: Mapped[str] = mapped_column(String(80), primary_key=True)
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pid: Mapped[int] = mapped_column(Integer)


class GuidedAsset(Base):
    __tablename__ = "guided_assets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    owner_id: Mapped[str] = mapped_column(String(64), index=True)
    asset_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(200))
    rights_statement: Mapped[str] = mapped_column(Text)
    consent_statement: Mapped[str] = mapped_column(Text)
    published: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class QuotaLock(Base):
    __tablename__ = "quota_locks"

    name: Mapped[str] = mapped_column(String(80), primary_key=True)

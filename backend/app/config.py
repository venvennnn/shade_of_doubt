from functools import lru_cache

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Documented SD actions for Skin Analysis API v2.1. HD names are a separate tier
# and must never be mixed into the same task.
SD_CONCERNS = (
    "wrinkle",
    "droopy_upper_eyelid",
    "droopy_lower_eyelid",
    "firmness",
    "acne",
    "moisture",
    "eye_bag",
    "dark_circle_v2",
    "age_spot",
    "radiance",
    "redness",
    "oiliness",
    "pore",
    "texture",
    "tear_trough",
    "skin_type",
)
HD_CONCERNS = (
    "hd_wrinkle",
    "hd_pore",
    "hd_texture",
    "hd_acne",
    "hd_oiliness",
    "hd_radiance",
    "hd_eye_bag",
    "hd_age_spot",
    "hd_dark_circle",
    "hd_droopy_upper_eyelid",
    "hd_droopy_lower_eyelid",
    "hd_firmness",
    "hd_moisture",
    "hd_redness",
    "hd_tear_trough",
    "hd_skin_type",
)

PIPELINE_VERSION = "sod-transform-1"
COLOUR_CONVERSION = "iec61966-2-1-srgb-linear"
RESIZE_METHOD = "pil-lanczos"
ENCODE_METHOD = "png-compress-level-3"
FORMULA_ID = "explicit-severity-match-v1"
SCHEMA_VERSION = "youcam-skin-json-2.1"
SCORE_DIRECTION_SOURCE = (
    "Perfect Corp AI Skin Analysis inputs and outputs: raw_score is a model output "
    "from 1 to 100, and a higher score indicates a healthier and more aesthetically "
    "pleasing skin condition in that documentation. It is not a physical measurement "
    "of redness, oil, or any other trait."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: str = "local"
    database_url: str = "postgresql+psycopg://shade:shade@localhost:5432/shade"
    frontend_origin: str = "http://localhost:3000"
    api_public_url: str = "http://localhost:8000"

    storage_backend: str = ""
    local_storage_dir: str = "./var/storage"

    youcam_api_key: str = ""
    youcam_base_url: str = "https://yce-api-01.makeupar.com"
    youcam_file_path: str = "/s2s/v2.0/file"
    youcam_task_path: str = "/s2s/v2.1/task/skin-analysis"
    youcam_concerns: str = "texture,pore,redness,oiliness,moisture,acne,age_spot"
    youcam_poll_interval_seconds: float = 10
    youcam_task_timeout_seconds: float = 600
    youcam_max_concurrency: int = 2
    youcam_webhook_secret: str = ""
    youcam_unit_cost_per_task: str = ""
    youcam_user_daily_unit_cap: int = 500
    youcam_global_daily_unit_cap: int = 5000
    youcam_enable_mask_overlay: bool = True
    quota_timezone: str = "UTC"

    min_valid_variants: int = 4
    default_top_k: int = 3
    retention_days: int = 30
    consent_version: str = "2026-11-01"
    normalize_long_side: int = 1280
    max_upload_bytes: int = 15_000_000
    max_provider_bytes: int = 10_000_000
    max_clip_fraction: float = 0.02
    framing_shift_fraction: float = 0.02
    exposure_low: float = 0.9
    exposure_high: float = 1.1
    warm_red_gain: float = 1.03
    warm_blue_gain: float = 0.97
    cool_red_gain: float = 0.97
    cool_blue_gain: float = 1.03
    score_direction: str = "higher_is_healthier"
    blur_variance_min: float = 60
    lighting_imbalance_max: float = 40
    capture_clip_fraction_max: float = 0.15

    worker_lease_seconds: int = 90
    worker_heartbeat_seconds: int = 15
    worker_max_attempts: int = 5
    worker_health_port: int = 8001
    worker_id: str = ""
    worker_idle_seconds: float = 2
    rate_limit_per_minute: int = 90
    operator_user_ids: str = ""

    @field_validator("database_url", mode="before")
    @classmethod
    def _psycopg_url(cls, value: str) -> str:
        if not isinstance(value, str):
            return value
        if value.startswith("postgres://"):
            value = "postgresql://" + value[len("postgres://") :]
        if value.startswith("postgresql://") and not value.startswith("postgresql+"):
            value = "postgresql+psycopg://" + value[len("postgresql://") :]
        return value

    @property
    def unit_cost(self) -> float | None:
        raw = self.youcam_unit_cost_per_task.strip()
        if not raw:
            return None
        return float(raw)

    @property
    def default_concerns(self) -> list[str]:
        return [part.strip() for part in self.youcam_concerns.split(",") if part.strip()]

    @property
    def operators(self) -> set[str]:
        return {part.strip() for part in self.operator_user_ids.split(",") if part.strip()}

    @property
    def resolved_storage_backend(self) -> str:
        if self.storage_backend:
            return self.storage_backend
        if self.environment == "local":
            return "local"
        return "database"


@lru_cache
def get_settings() -> Settings:
    return Settings()

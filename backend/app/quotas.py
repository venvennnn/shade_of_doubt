import zlib
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import case, func, select, text
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import QuotaError
from app.models import QuotaLock, UsageLedger, utcnow
from app.youcam import assert_pricing_configured


def quota_day(settings: Settings, moment: datetime | None = None):
    moment = moment or utcnow()
    try:
        zone = ZoneInfo(settings.quota_timezone or "UTC")
    except Exception:
        zone = ZoneInfo("UTC")
    return moment.astimezone(zone).date()


def _lock(session: Session, name: str) -> None:
    bind = session.get_bind()
    if bind.dialect.name == "postgresql":
        key = zlib.crc32(name.encode()) & 0x7FFFFFFF
        session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": key})
        return
    existing = session.get(QuotaLock, name)
    if existing is None:
        session.add(QuotaLock(name=name))
        session.flush()
    session.execute(select(QuotaLock).where(QuotaLock.name == name).with_for_update())


def net_units(session: Session, day, owner_id: str | None = None) -> float:
    amount = case(
        (UsageLedger.kind == "reserve", UsageLedger.units_estimated),
        (UsageLedger.kind == "release", -UsageLedger.units_estimated),
        else_=0,
    )
    query = select(func.coalesce(func.sum(amount), 0)).where(UsageLedger.day == day)
    if owner_id is not None:
        query = query.where(UsageLedger.owner_id == owner_id)
    return float(session.execute(query).scalar_one())


def reserve_units(session: Session, settings: Settings, owner_id: str, experiment_id: str, task_count: int) -> float:
    cost = assert_pricing_configured(settings)
    units = cost * task_count
    day = quota_day(settings)
    _lock(session, "quota-global")
    _lock(session, f"quota-user-{owner_id}")
    user_used = net_units(session, day, owner_id)
    global_used = net_units(session, day, None)
    if user_used + units > settings.youcam_user_daily_unit_cap:
        raise QuotaError(
            "user_daily_cap",
            "This run would pass the per-user daily unit cap.",
            "Wait until the next quota day or lower the experiment size. The quota day uses "
            f"{settings.quota_timezone}.",
            {"used": user_used, "requested": units, "cap": settings.youcam_user_daily_unit_cap},
        )
    if global_used + units > settings.youcam_global_daily_unit_cap:
        raise QuotaError(
            "global_daily_cap",
            "This run would pass the global daily unit cap.",
            "Wait until the next quota day. No task was submitted.",
            {"used": global_used, "requested": units, "cap": settings.youcam_global_daily_unit_cap},
        )
    session.add(
        UsageLedger(
            id=_id(),
            owner_id=owner_id,
            experiment_id=experiment_id,
            day=day,
            kind="reserve",
            units_estimated=units,
            units_confirmed=None,
            note="reserved before submission; confirmed provider charges are not returned by the status API",
        )
    )
    session.flush()
    return units


def release_units(session: Session, settings: Settings, owner_id: str, experiment_id: str, units: float, note: str) -> None:
    if units <= 0:
        return
    session.add(
        UsageLedger(
            id=_id(),
            owner_id=owner_id,
            experiment_id=experiment_id,
            day=quota_day(settings),
            kind="release",
            units_estimated=units,
            units_confirmed=None,
            note=note,
        )
    )
    session.flush()


def _id() -> str:
    import uuid

    return str(uuid.uuid4())

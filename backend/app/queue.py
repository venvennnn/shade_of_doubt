from datetime import timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import Job, utcnow


def recover_expired_leases(session: Session) -> int:
    now = utcnow()
    expired = session.query(Job).filter(Job.status == "leased", Job.lease_expires_at.is_not(None), Job.lease_expires_at < now).all()
    recovered = 0
    for job in expired:
        job.attempts += 1
        job.lease_owner = None
        job.lease_expires_at = None
        job.updated_at = now
        if job.attempts >= job.max_attempts:
            job.status = "dead"
            job.last_error = "lease expired and retries were exhausted"
        else:
            job.status = "queued"
            job.run_after = now
            job.last_error = "lease expired; job returned to the queue"
            recovered += 1
    session.flush()
    return recovered


def claim_job(session: Session, worker_id: str, settings: Settings) -> Job | None:
    recover_expired_leases(session)
    now = utcnow()
    expires = now + timedelta(seconds=settings.worker_lease_seconds)
    dialect = session.get_bind().dialect.name
    if dialect == "postgresql":
        row = session.execute(
            text(
                """
                WITH cte AS (
                    SELECT id FROM jobs
                    WHERE status = 'queued' AND run_after <= :now
                    ORDER BY created_at
                    FOR UPDATE SKIP LOCKED
                    LIMIT 1
                )
                UPDATE jobs AS j
                SET status = 'leased',
                    lease_owner = :worker,
                    lease_expires_at = :expires,
                    heartbeat_at = :now,
                    updated_at = :now
                FROM cte
                WHERE j.id = cte.id
                RETURNING j.id
                """
            ),
            {"now": now, "worker": worker_id, "expires": expires},
        ).first()
        session.flush()
        if row is None:
            return None
        return session.get(Job, row[0])
    job = (
        session.query(Job)
        .filter(Job.status == "queued", Job.run_after <= now)
        .order_by(Job.created_at)
        .first()
    )
    if job is None:
        return None
    job.status = "leased"
    job.lease_owner = worker_id
    job.lease_expires_at = expires
    job.heartbeat_at = now
    job.updated_at = now
    session.flush()
    return job


def heartbeat_job(session: Session, job_id: str, worker_id: str, settings: Settings) -> None:
    job = session.get(Job, job_id)
    if job is None or job.status != "leased" or job.lease_owner != worker_id:
        return
    now = utcnow()
    job.heartbeat_at = now
    job.lease_expires_at = now + timedelta(seconds=settings.worker_lease_seconds)
    job.updated_at = now
    session.flush()


def finish_job(session: Session, job: Job, status: str, error: str | None = None, delay_seconds: float | None = None) -> None:
    now = utcnow()
    job.updated_at = now
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = error
    if status == "wait":
        job.status = "queued"
        job.run_after = now + timedelta(seconds=delay_seconds or 10)
    elif status == "retry":
        job.attempts += 1
        if job.attempts >= job.max_attempts:
            job.status = "dead"
        else:
            job.status = "queued"
            job.run_after = now + timedelta(seconds=delay_seconds or 15)
    else:
        job.status = status
    session.flush()

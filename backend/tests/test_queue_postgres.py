import os
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.config import get_settings
from app.db import Base
from app.models import Job, utcnow
from app.queue import claim_job, recover_expired_leases


def _postgres_url() -> str | None:
    url = os.environ.get("TEST_DATABASE_URL")
    if url and url.startswith("postgresql"):
        return url
    return None


@pytest.fixture
def pg_session():
    url = _postgres_url()
    if not url:
        pytest.skip("TEST_DATABASE_URL is not a PostgreSQL URL")
    engine = create_engine(url)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def test_skip_locked_claim_and_lease_recovery(pg_session):
    settings = get_settings()
    job = Job(
        id=str(uuid.uuid4()),
        owner_id="user-a",
        experiment_id=None,
        kind="experiment",
        status="queued",
        payload_json={"experiment_id": "exp"},
        max_attempts=3,
        run_after=utcnow(),
    )
    pg_session.add(job)
    pg_session.commit()
    first = claim_job(pg_session, "worker-a", settings)
    pg_session.commit()
    assert first is not None
    second = claim_job(pg_session, "worker-b", settings)
    pg_session.commit()
    assert second is None
    first.lease_expires_at = utcnow() - timedelta(seconds=5)
    pg_session.commit()
    recovered = recover_expired_leases(pg_session)
    pg_session.commit()
    assert recovered == 1
    pg_session.refresh(first)
    assert first.status == "queued"
    assert first.attempts == 1
    again = claim_job(pg_session, "worker-b", settings)
    pg_session.commit()
    assert again is not None
    assert again.id == job.id

import pytest

from app.auth import principal_from_session
from app.config import Settings
from app.db import Base, get_engine, reset_engine
from app.errors import AuthError
from app.main import get_principal
from app.storage import DatabaseStorage


def test_browser_session_is_stable_and_unrelated_to_the_raw_token():
    first = principal_from_session("a" * 32)
    assert first.user_id == principal_from_session("a" * 32).user_id
    assert first.user_id != principal_from_session("b" * 32).user_id
    assert len(first.user_id) == 64
    assert "a" * 32 not in first.user_id
    with pytest.raises(AuthError):
        principal_from_session("short")
    with pytest.raises(AuthError):
        get_principal(None)


def test_railway_postgres_url_uses_psycopg():
    rewritten = Settings(database_url="postgres://shade:secret@db.internal:5432/railway")
    assert rewritten.database_url == "postgresql+psycopg://shade:secret@db.internal:5432/railway"
    explicit = Settings(database_url="postgresql+psycopg://shade:secret@db.internal:5432/railway")
    assert explicit.database_url == "postgresql+psycopg://shade:secret@db.internal:5432/railway"
    assert Settings(environment="production", storage_backend="").resolved_storage_backend == "database"
    assert Settings(environment="local", storage_backend="").resolved_storage_backend == "local"


def test_database_storage_roundtrip():
    reset_engine()
    engine = get_engine()
    Base.metadata.create_all(engine)
    storage = DatabaseStorage()
    storage.put("owners/a/selfie.png", b"png-bytes", "image/png")
    assert storage.get("owners/a/selfie.png") == b"png-bytes"
    storage.put("owners/a/selfie.png", b"replaced", "image/png")
    assert storage.get("owners/a/selfie.png") == b"replaced"
    storage.delete("owners/a/selfie.png")
    with pytest.raises(FileNotFoundError):
        storage.get("owners/a/selfie.png")

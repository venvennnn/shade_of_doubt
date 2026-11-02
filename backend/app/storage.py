from pathlib import Path

from app.config import Settings
from app.db import session_factory
from app.errors import ConfigurationError
from app.models import StoredObject


class Storage:
    def put(self, path: str, data: bytes, content_type: str) -> None:
        raise NotImplementedError

    def get(self, path: str) -> bytes:
        raise NotImplementedError

    def delete(self, path: str) -> None:
        raise NotImplementedError


class LocalStorage(Storage):
    def __init__(self, root: str):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, path: str) -> Path:
        target = (self.root / path).resolve()
        if self.root.resolve() not in target.parents and target != self.root.resolve():
            raise ConfigurationError("storage_path_invalid", "Storage path escaped the local root.", "")
        target.parent.mkdir(parents=True, exist_ok=True)
        return target

    def put(self, path: str, data: bytes, content_type: str) -> None:
        self._path(path).write_bytes(data)

    def get(self, path: str) -> bytes:
        return self._path(path).read_bytes()

    def delete(self, path: str) -> None:
        target = self._path(path)
        if target.exists():
            target.unlink()


class DatabaseStorage(Storage):
    """Photograph bytes in Postgres so the API and worker share one store."""

    def put(self, path: str, data: bytes, content_type: str) -> None:
        session = session_factory()()
        try:
            row = session.get(StoredObject, path)
            if row is None:
                session.add(StoredObject(path=path, content=data, content_type=content_type))
            else:
                row.content = data
                row.content_type = content_type
            session.commit()
        finally:
            session.close()

    def get(self, path: str) -> bytes:
        session = session_factory()()
        try:
            row = session.get(StoredObject, path)
            if row is None:
                raise FileNotFoundError(path)
            return bytes(row.content)
        finally:
            session.close()

    def delete(self, path: str) -> None:
        session = session_factory()()
        try:
            row = session.get(StoredObject, path)
            if row is not None:
                session.delete(row)
                session.commit()
        finally:
            session.close()


def build_storage(settings: Settings) -> Storage:
    backend = settings.resolved_storage_backend
    if backend == "local":
        return LocalStorage(settings.local_storage_dir)
    if backend == "database":
        return DatabaseStorage()
    raise ConfigurationError(
        "storage_unconfigured",
        "No storage backend is configured.",
        "Set STORAGE_BACKEND=database on Railway, or STORAGE_BACKEND=local when the API and worker share a disk.",
    )

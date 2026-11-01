from pathlib import Path

import httpx

from app.config import Settings
from app.errors import ConfigurationError


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


class SupabaseStorage(Storage):
    def __init__(self, settings: Settings):
        if not settings.supabase_url or not settings.supabase_service_role_key:
            raise ConfigurationError(
                "storage_unconfigured",
                "Supabase Storage is selected but the URL or service role key is missing.",
                "Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY. The service role key stays on the server.",
            )
        self.base = settings.supabase_url.rstrip("/") + "/storage/v1"
        self.bucket = settings.supabase_storage_bucket
        self.key = settings.supabase_service_role_key
        self.http = httpx.Client(timeout=60.0)

    def _headers(self, content_type: str | None = None) -> dict:
        headers = {"Authorization": f"Bearer {self.key}", "apikey": self.key}
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    def put(self, path: str, data: bytes, content_type: str) -> None:
        response = self.http.post(
            f"{self.base}/object/{self.bucket}/{path}",
            content=data,
            headers={**self._headers(content_type), "x-upsert": "true"},
        )
        if response.status_code >= 400:
            raise ConfigurationError(
                "storage_write_failed",
                "Private storage rejected the upload.",
                "Check the bucket exists, is private, and the service role can write to it.",
            )

    def get(self, path: str) -> bytes:
        response = self.http.get(f"{self.base}/object/{self.bucket}/{path}", headers=self._headers())
        if response.status_code >= 400:
            raise ConfigurationError("storage_read_failed", "Private storage could not read that object.", "")
        return response.content

    def delete(self, path: str) -> None:
        response = self.http.request(
            "DELETE",
            f"{self.base}/object/{self.bucket}",
            headers={**self._headers("application/json")},
            json={"prefixes": [path]},
        )
        if response.status_code >= 400:
            raise ConfigurationError("storage_delete_failed", "Private storage could not delete that object.", "")


def build_storage(settings: Settings) -> Storage:
    backend = settings.resolved_storage_backend
    if backend == "local":
        return LocalStorage(settings.local_storage_dir)
    if backend == "supabase":
        return SupabaseStorage(settings)
    raise ConfigurationError(
        "storage_unconfigured",
        "No storage backend is configured.",
        "For production set SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY, and SUPABASE_STORAGE_BUCKET. "
        "Local Compose may set STORAGE_BACKEND=local.",
    )

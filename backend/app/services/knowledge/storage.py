"""File storage for uploaded knowledge documents.

Defined as an interface with a local-filesystem implementation because
that's genuinely useful for self-hosted/dev deployments — swapping in
an S3Storage later (for the hosted SaaS deployment) means implementing
this same interface and changing one line in get_storage_backend(),
not touching any calling code in KnowledgeService.
"""
import uuid
from abc import ABC, abstractmethod
from pathlib import Path

from app.config import settings


class StorageBackend(ABC):
    @abstractmethod
    async def save(self, owner_id: uuid.UUID, filename: str, content: bytes) -> str:
        """Persists content, returns an opaque path/key to pass to read()/delete() later."""
        raise NotImplementedError

    @abstractmethod
    async def read(self, path: str) -> bytes:
        raise NotImplementedError

    @abstractmethod
    async def delete(self, path: str) -> None:
        raise NotImplementedError


class LocalStorageBackend(StorageBackend):
    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(base_dir or settings.STORAGE_DIR)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve(self, path: str) -> Path:
        resolved = (self.base_dir / path).resolve()
        if self.base_dir.resolve() not in resolved.parents and resolved != self.base_dir.resolve():
            raise ValueError("Resolved storage path escapes the storage root")
        return resolved

    async def save(self, owner_id: uuid.UUID, filename: str, content: bytes) -> str:
        safe_name = Path(filename).name  # strip any path components from the original filename
        relative_path = f"{owner_id}/{uuid.uuid4()}_{safe_name}"
        full_path = self._resolve(relative_path)
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_bytes(content)
        return relative_path

    async def read(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def delete(self, path: str) -> None:
        full_path = self._resolve(path)
        if full_path.exists():
            full_path.unlink()


_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    global _backend_instance
    if _backend_instance is None:
        if settings.STORAGE_BACKEND == "local":
            _backend_instance = LocalStorageBackend()
        else:
            raise ValueError(
                f"Unknown STORAGE_BACKEND '{settings.STORAGE_BACKEND}'. "
                f"Only 'local' is implemented — implement StorageBackend for S3/etc. and register it here."
            )
    return _backend_instance

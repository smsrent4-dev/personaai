"""File storage abstraction for uploaded files.

Supports:

- Local filesystem storage for development/self-hosted deployments.
- Cloudinary storage for hosted production deployments.

Cloudinary is used as persistent object/media storage so uploaded files
are not lost when a Railway service/container is restarted or redeployed.
"""

from __future__ import annotations

import mimetypes
import uuid
from abc import ABC, abstractmethod
from pathlib import Path
from urllib.parse import urlparse

import cloudinary
import cloudinary.uploader
import httpx

from app.config import settings


class StorageBackend(ABC):
    """Common interface used by knowledge documents and product images."""

    @abstractmethod
    async def save(
        self,
        owner_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Persist content and return a storage reference."""
        raise NotImplementedError

    @abstractmethod
    async def read(self, path: str) -> bytes:
        """Read previously stored content."""
        raise NotImplementedError

    @abstractmethod
    async def delete(self, path: str) -> None:
        """Delete previously stored content."""
        raise NotImplementedError

    async def get_url(self, path: str) -> str | None:
        """Return a public URL when the backend supports one."""
        return None


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage for development/self-hosted use."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(
            base_dir or settings.STORAGE_DIR
        )

        self.base_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _resolve(self, path: str) -> Path:
        resolved = (
            self.base_dir / path
        ).resolve()

        base = self.base_dir.resolve()

        if base not in resolved.parents and resolved != base:
            raise ValueError(
                "Resolved storage path escapes the storage root"
            )

        return resolved

    async def save(
        self,
        owner_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> str:
        safe_name = Path(filename).name

        relative_path = (
            f"{owner_id}/"
            f"{uuid.uuid4()}_"
            f"{safe_name}"
        )

        full_path = self._resolve(relative_path)

        full_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        full_path.write_bytes(content)

        return relative_path

    async def read(self, path: str) -> bytes:
        return self._resolve(path).read_bytes()

    async def delete(self, path: str) -> None:
        full_path = self._resolve(path)

        if full_path.exists():
            full_path.unlink()

    async def get_url(self, path: str) -> str | None:
        return None


class CloudinaryStorageBackend(StorageBackend):
    """Persistent Cloudinary-backed storage.

    Files are organized by owner:

        personaai/{owner_id}/...

    Cloudinary's secure HTTPS URL is stored as the storage reference.

    This is intentionally URL-based because Cloudinary is responsible for
    persistent storage and delivery.
    """

    def __init__(self):
        if not settings.CLOUDINARY_CLOUD_NAME:
            raise ValueError(
                "CLOUDINARY_CLOUD_NAME is not configured."
            )

        if not settings.CLOUDINARY_API_KEY:
            raise ValueError(
                "CLOUDINARY_API_KEY is not configured."
            )

        if not settings.CLOUDINARY_API_SECRET:
            raise ValueError(
                "CLOUDINARY_API_SECRET is not configured."
            )

        cloudinary.config(
            cloud_name=settings.CLOUDINARY_CLOUD_NAME,
            api_key=settings.CLOUDINARY_API_KEY,
            api_secret=settings.CLOUDINARY_API_SECRET,
            secure=True,
        )

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Remove directory components and unsafe characters."""

        name = Path(filename).name

        if not name:
            name = "file"

        # Keep the filename simple and Cloudinary-friendly.
        safe_chars = []

        for char in name:
            if (
                char.isalnum()
                or char in {
                    ".",
                    "-",
                    "_",
                }
            ):
                safe_chars.append(char)
            else:
                safe_chars.append("_")

        return "".join(safe_chars)

    @staticmethod
    def _resource_type(filename: str) -> str:
        """Choose an appropriate Cloudinary resource type."""

        content_type = (
            mimetypes.guess_type(filename)[0]
            or ""
        ).lower()

        if content_type.startswith("image/"):
            return "image"

        if content_type.startswith("video/"):
            return "video"

        return "raw"

    async def save(
        self,
        owner_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> str:
        safe_name = self._safe_filename(filename)

        public_id = (
            f"personaai/"
            f"{owner_id}/"
            f"{uuid.uuid4()}_{safe_name}"
        )

        resource_type = self._resource_type(
            safe_name
        )

        try:
            result = await cloudinary.uploader.upload(
                content,
                public_id=public_id,
                resource_type=resource_type,
                overwrite=False,
                unique_filename=False,
                use_filename=False,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Cloudinary upload failed: {exc}"
            ) from exc

        secure_url = result.get("secure_url")

        if not secure_url:
            raise RuntimeError(
                "Cloudinary upload succeeded but no secure_url "
                "was returned."
            )

        return secure_url

    async def read(self, path: str) -> bytes:
        """Download a file from its Cloudinary HTTPS URL."""

        if not path.startswith(("http://", "https://")):
            raise ValueError(
                "Cloudinary storage reference must be an HTTP(S) URL."
            )

        try:
            async with httpx.AsyncClient(
                timeout=30.0,
                follow_redirects=True,
            ) as client:
                response = await client.get(path)
                response.raise_for_status()
                return response.content

        except httpx.HTTPError as exc:
            raise RuntimeError(
                f"Could not download Cloudinary file: {exc}"
            ) from exc

    async def delete(self, path: str) -> None:
        """Delete a Cloudinary asset.

        The URL is converted back into the Cloudinary public ID.
        """

        if not path.startswith(("http://", "https://")):
            raise ValueError(
                "Cloudinary storage reference must be an HTTP(S) URL."
            )

        parsed = urlparse(path)

        # Cloudinary URL pattern:
        #
        # /<resource_type>/upload/v<version>/<public_id>
        #
        # Example:
        # /image/upload/v123/personaai/owner/id_file.jpg

        path_parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        try:
            upload_index = path_parts.index("upload")
        except ValueError:
            raise ValueError(
                "Invalid Cloudinary URL."
            )

        asset_parts = path_parts[
            upload_index + 1:
        ]

        if not asset_parts:
            raise ValueError(
                "Could not determine Cloudinary asset."
            )

        # Remove version component if present.
        if asset_parts[0].startswith("v") and asset_parts[0][1:].isdigit():
            asset_parts = asset_parts[1:]

        public_id = "/".join(asset_parts)

        # Remove extension for image/raw public IDs where appropriate.
        #
        # Cloudinary normally identifies the asset by public_id without
        # the delivery extension.
        resource_type = (
            path_parts[upload_index - 1]
            if upload_index > 0
            else "image"
        )

        if resource_type not in {
            "image",
            "video",
            "raw",
        }:
            resource_type = "image"

        if resource_type != "raw":
            public_id = str(
                Path(public_id).with_suffix("")
            )

        try:
            await cloudinary.uploader.destroy(
                public_id,
                resource_type=resource_type,
                invalidate=True,
            )
        except Exception as exc:
            raise RuntimeError(
                f"Cloudinary delete failed: {exc}"
            ) from exc

    async def get_url(self, path: str) -> str | None:
        if path.startswith(("http://", "https://")):
            return path

        return None


_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend."""

    global _backend_instance

    if _backend_instance is not None:
        return _backend_instance

    backend = settings.STORAGE_BACKEND.lower().strip()

    if backend == "local":
        _backend_instance = LocalStorageBackend()

    elif backend == "cloudinary":
        _backend_instance = CloudinaryStorageBackend()

    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND '{settings.STORAGE_BACKEND}'. "
            "Supported values are 'local' and 'cloudinary'."
        )

    return _backend_instance

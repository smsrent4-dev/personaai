"""Persistent file storage abstraction.

Supports:

- Local filesystem storage for development/self-hosted deployments.
- Cloudinary storage for hosted production deployments.

Cloudinary is used for production media/file persistence so uploaded
files survive Railway container restarts and redeployments.

The Cloudinary implementation also keeps backwards compatibility with
legacy local-storage references already stored in the database.
"""

from __future__ import annotations

import asyncio
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
    """Common storage interface used by documents and product images."""

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
        """Return a public URL when supported by the backend."""
        return None


# ---------------------------------------------------------------------------
# Local storage
# ---------------------------------------------------------------------------


class LocalStorageBackend(StorageBackend):
    """Local filesystem storage for development/self-hosted deployments."""

    def __init__(self, base_dir: str | None = None):
        self.base_dir = Path(
            base_dir or settings.STORAGE_DIR
        ).resolve()

        self.base_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

    def _resolve(self, path: str) -> Path:
        """Safely resolve a path inside the storage directory."""

        # Local storage references must be relative paths.
        if Path(path).is_absolute():
            raise ValueError(
                "Absolute storage paths are not allowed."
            )

        resolved = (
            self.base_dir / path
        ).resolve()

        base = self.base_dir

        if base not in resolved.parents and resolved != base:
            raise ValueError(
                "Resolved storage path escapes the storage root."
            )

        return resolved

    async def save(
        self,
        owner_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> str:
        safe_name = Path(filename).name or "file"

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


# ---------------------------------------------------------------------------
# Cloudinary storage
# ---------------------------------------------------------------------------


class CloudinaryStorageBackend(StorageBackend):
    """Persistent Cloudinary-backed storage.

    New files are uploaded under:

        personaai/{owner_id}/{uuid}_{filename}

    The returned storage reference is the Cloudinary secure HTTPS URL.

    Legacy local-storage references are still supported for reading and
    deleting where the local file exists.
    """

    _CLOUDINARY_HOST_SUFFIX = "res.cloudinary.com"

    def __init__(self):
        cloud_name = (
            settings.CLOUDINARY_CLOUD_NAME or ""
        ).strip()

        api_key = (
            settings.CLOUDINARY_API_KEY or ""
        ).strip()

        api_secret = (
            settings.CLOUDINARY_API_SECRET or ""
        ).strip()

        if not cloud_name:
            raise ValueError(
                "CLOUDINARY_CLOUD_NAME is not configured."
            )

        if not api_key:
            raise ValueError(
                "CLOUDINARY_API_KEY is not configured."
            )

        if not api_secret:
            raise ValueError(
                "CLOUDINARY_API_SECRET is not configured."
            )

        cloudinary.config(
            cloud_name=cloud_name,
            api_key=api_key,
            api_secret=api_secret,
            secure=True,
        )

        self.cloud_name = cloud_name

        # Used only for backwards compatibility with files that were
        # uploaded before switching to Cloudinary.
        self._legacy_local = LocalStorageBackend()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_filename(filename: str) -> str:
        """Return a safe filename suitable for Cloudinary public IDs."""

        name = Path(filename).name

        if not name:
            name = "file"

        safe_chars: list[str] = []

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

        result = "".join(safe_chars).strip("._")

        return result or "file"

    @staticmethod
    def _resource_type(filename: str) -> str:
        """Determine Cloudinary resource type from filename."""

        content_type = (
            mimetypes.guess_type(filename)[0]
            or ""
        ).lower()

        if content_type.startswith("image/"):
            return "image"

        if content_type.startswith("video/"):
            return "video"

        return "raw"

    @classmethod
    def _is_cloudinary_url(cls, value: str) -> bool:
        """Return True when value is a Cloudinary delivery URL."""

        try:
            parsed = urlparse(value)

            if parsed.scheme not in {
                "http",
                "https",
            }:
                return False

            hostname = (
                parsed.hostname or ""
            ).lower()

            return hostname.endswith(
                cls._CLOUDINARY_HOST_SUFFIX
            )

        except Exception:
            return False

    @staticmethod
    def _parse_cloudinary_reference(
        url: str,
    ) -> tuple[str, str]:
        """Extract resource type and public ID from a Cloudinary URL.

        Expected delivery structure:

            https://res.cloudinary.com/<cloud>/image/upload/v123/path/file.jpg

        Transformations are deliberately rejected here because Product.images
        stores the original secure_url returned by Cloudinary.
        """

        parsed = urlparse(url)

        path_parts = [
            part
            for part in parsed.path.split("/")
            if part
        ]

        if len(path_parts) < 4:
            raise ValueError(
                "Invalid Cloudinary URL."
            )

        # Locate the upload marker.
        try:
            upload_index = path_parts.index(
                "upload"
            )
        except ValueError as exc:
            raise ValueError(
                "Invalid Cloudinary URL: missing upload path."
            ) from exc

        if upload_index == 0:
            raise ValueError(
                "Invalid Cloudinary URL: missing resource type."
            )

        resource_type = path_parts[
            upload_index - 1
        ]

        if resource_type not in {
            "image",
            "video",
            "raw",
        }:
            raise ValueError(
                f"Unsupported Cloudinary resource type: "
                f"{resource_type}"
            )

        asset_parts = path_parts[
            upload_index + 1:
        ]

        if not asset_parts:
            raise ValueError(
                "Invalid Cloudinary URL: missing asset."
            )

        # If a version is present, remove it.
        if (
            asset_parts
            and asset_parts[0].startswith("v")
            and asset_parts[0][1:].isdigit()
        ):
            asset_parts = asset_parts[1:]

        if not asset_parts:
            raise ValueError(
                "Invalid Cloudinary URL: missing public ID."
            )

        # We intentionally do not support transformation URLs here.
        #
        # Product.images stores Cloudinary's original secure_url, so the
        # first path segment after /upload/ should be our public ID.
        public_id = "/".join(asset_parts)

        if resource_type in {
            "image",
            "video",
        }:
            # Cloudinary image/video public IDs normally exclude the
            # delivery extension.
            public_id = str(
                Path(public_id).with_suffix("")
            )

        return resource_type, public_id

    # ------------------------------------------------------------------
    # Save
    # ------------------------------------------------------------------

    async def save(
        self,
        owner_id: uuid.UUID,
        filename: str,
        content: bytes,
    ) -> str:
        """Upload a file to Cloudinary and return its secure URL."""

        if not content:
            raise ValueError(
                "Cannot upload an empty file."
            )

        safe_name = self._safe_filename(
            filename
        )

        resource_type = self._resource_type(
            safe_name
        )

        public_id = (
            f"personaai/"
            f"{owner_id}/"
            f"{uuid.uuid4()}_"
            f"{safe_name}"
        )

        try:
            # cloudinary.uploader.upload() is synchronous.
            #
            # Run it in a worker thread so it does not block FastAPI's
            # async event loop.
            result = await asyncio.to_thread(
                cloudinary.uploader.upload,
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

        secure_url = result.get(
            "secure_url"
        )

        if not secure_url:
            raise RuntimeError(
                "Cloudinary upload succeeded but "
                "no secure_url was returned."
            )

        return str(secure_url)

    # ------------------------------------------------------------------
    # Read
    # ------------------------------------------------------------------

    async def read(self, path: str) -> bytes:
        """Read a Cloudinary file or legacy local file."""

        # Cloudinary URL
        if self._is_cloudinary_url(path):
            try:
                async with httpx.AsyncClient(
                    timeout=30.0,
                    follow_redirects=True,
                ) as client:
                    response = await client.get(
                        path
                    )

                    response.raise_for_status()

                    if not response.content:
                        raise RuntimeError(
                            "Cloudinary returned an empty file."
                        )

                    return response.content

            except httpx.HTTPError as exc:
                raise RuntimeError(
                    f"Could not download Cloudinary file: {exc}"
                ) from exc

        # Legacy local-storage reference.
        #
        # This allows existing database records such as:
        #
        # https://your-api/api/v1/products/images/<owner>/<file>
        #
        # to continue working where the old local file still exists.
        try:
            return await self._legacy_local.read(
                path
            )

        except FileNotFoundError as exc:
            raise FileNotFoundError(
                f"Stored file was not found: {path}"
            ) from exc

    # ------------------------------------------------------------------
    # Delete
    # ------------------------------------------------------------------

    async def delete(self, path: str) -> None:
        """Delete a Cloudinary asset or legacy local file."""

        # New Cloudinary asset
        if self._is_cloudinary_url(path):
            try:
                resource_type, public_id = (
                    self._parse_cloudinary_reference(
                        path
                    )
                )

                result = await asyncio.to_thread(
                    cloudinary.uploader.destroy,
                    public_id,
                    resource_type=resource_type,
                    invalidate=True,
                )

            except Exception as exc:
                raise RuntimeError(
                    f"Cloudinary delete failed: {exc}"
                ) from exc

            result_status = result.get(
                "result"
            )

            # Cloudinary commonly returns:
            #
            # "ok"       -> deleted
            # "not found" -> already absent
            #
            # Treat both as safe deletion states.
            if result_status not in {
                "ok",
                "not found",
            }:
                raise RuntimeError(
                    "Cloudinary did not confirm deletion. "
                    f"Response: {result}"
                )

            return

        # Legacy local file.
        #
        # This is deliberately best-effort. If an old local file has
        # already disappeared because its Railway container was replaced,
        # removing the database reference should still be possible.
        try:
            await self._legacy_local.delete(
                path
            )
        except (
            FileNotFoundError,
            ValueError,
        ):
            pass

    # ------------------------------------------------------------------
    # Public URL
    # ------------------------------------------------------------------

    async def get_url(
        self,
        path: str,
    ) -> str | None:
        """Return a usable public URL for a stored reference."""

        if path.startswith(
            (
                "http://",
                "https://",
            )
        ):
            return path

        # Legacy local storage references do not have a direct public URL
        # at the storage layer. ProductService handles their API URL.
        return None


# ---------------------------------------------------------------------------
# Backend factory
# ---------------------------------------------------------------------------


_backend_instance: StorageBackend | None = None


def get_storage_backend() -> StorageBackend:
    """Return the configured storage backend.

    The instance is cached so the application does not repeatedly
    configure Cloudinary on every request.
    """

    global _backend_instance

    if _backend_instance is not None:
        return _backend_instance

    backend = (
        settings.STORAGE_BACKEND
        .lower()
        .strip()
    )

    if backend == "local":
        _backend_instance = (
            LocalStorageBackend()
        )

    elif backend == "cloudinary":
        _backend_instance = (
            CloudinaryStorageBackend()
        )

    else:
        raise ValueError(
            f"Unknown STORAGE_BACKEND "
            f"'{settings.STORAGE_BACKEND}'. "
            "Supported values are 'local' and 'cloudinary'."
        )

    return _backend_instance

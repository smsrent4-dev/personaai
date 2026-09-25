"""Telegram implementation of PlatformAdapter.

Talks to the Telegram Bot API directly over httpx.

The adapter supports:
- Sending text messages.
- Sending product images.
- Downloading incoming Telegram media.
- Telegram webhook management.
- Parsing text, photo, document, voice, and location messages.

Product images are uploaded to Telegram as multipart bytes rather than
passing the backend image URL directly to Telegram. This avoids Telegram
errors such as:

    Bad Request: failed to get HTTP URL content

when Telegram's servers cannot fetch the application's image URL.
"""

import mimetypes
from pathlib import Path
from urllib.parse import urlparse

import httpx

from app.models.message import MessageType
from app.services.platforms.base import IncomingMessage, PlatformAdapter


TELEGRAM_API_BASE = "https://api.telegram.org"

_EXTENSION_MIME_OVERRIDES = {
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
}

_ALLOWED_IMAGE_CONTENT_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/gif",
}

_MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 MB


class TelegramAPIError(Exception):
    """Raised when Telegram's Bot API returns an unsuccessful response."""

    pass


class TelegramAdapter(PlatformAdapter):
    platform_name = "telegram"

    def __init__(
        self,
        bot_token: str,
        timeout: float = 15.0,
    ):
        self.bot_token = bot_token

        # Main Telegram Bot API client.
        self._client = httpx.AsyncClient(
            base_url=f"{TELEGRAM_API_BASE}/bot{bot_token}",
            timeout=timeout,
        )

        # Separate client for fetching product images from our backend.
        #
        # This is intentionally separate from the Telegram API client
        # because product image URLs belong to the application/backend,
        # not to api.telegram.org.
        self._media_client = httpx.AsyncClient(
            timeout=30.0,
            follow_redirects=True,
        )

    async def aclose(self) -> None:
        """Close both HTTP clients."""

        await self._client.aclose()
        await self._media_client.aclose()

    # ------------------------------------------------------------------
    # outgoing text
    # ------------------------------------------------------------------

    async def send_text(
        self,
        external_conversation_id: str,
        text: str,
    ) -> None:
        """Send a Telegram text message.

        Telegram has a 4096-character message limit, so long messages
        are split into multiple messages.
        """

        for part in _split_for_telegram(text):
            resp = await self._client.post(
                "/sendMessage",
                json={
                    "chat_id": external_conversation_id,
                    "text": part,
                },
            )

            data = _safe_json(resp)

            if not data.get("ok"):
                raise TelegramAPIError(
                    f"sendMessage failed: {data}"
                )

    # ------------------------------------------------------------------
    # outgoing photo
    # ------------------------------------------------------------------

    async def send_photo(
        self,
        external_conversation_id: str,
        image_url: str,
        caption: str | None = None,
    ) -> None:
        """Send an image to Telegram.

        Instead of asking Telegram to fetch `image_url` itself, this method:

        1. Downloads the image from the application's backend.
        2. Validates the response.
        3. Uploads the raw image bytes to Telegram using multipart/form-data.

        This is more reliable for private/internal/backend URLs and avoids
        Telegram's:

            failed to get HTTP URL content

        error.
        """

        if not image_url:
            raise TelegramAPIError(
                "sendPhoto failed: image URL is empty"
            )

        image_bytes, mime_type, filename = (
            await self._download_image_for_upload(image_url)
        )

        if len(image_bytes) > _MAX_IMAGE_SIZE:
            raise TelegramAPIError(
                "Product image is too large for Telegram upload "
                f"({len(image_bytes)} bytes). Maximum allowed is "
                f"{_MAX_IMAGE_SIZE} bytes."
            )

        if mime_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            raise TelegramAPIError(
                f"Unsupported product image MIME type: {mime_type}"
            )

        data = {
            "chat_id": external_conversation_id,
        }

        if caption:
            # Telegram photo captions have a 1024-character limit.
            data["caption"] = caption[:1024]

        files = {
            "photo": (
                filename,
                image_bytes,
                mime_type,
            )
        }

        resp = await self._client.post(
            "/sendPhoto",
            data=data,
            files=files,
        )

        response_data = _safe_json(resp)

        if not response_data.get("ok"):
            raise TelegramAPIError(
                f"sendPhoto failed: {response_data}"
            )

    async def _download_image_for_upload(
        self,
        image_url: str,
    ) -> tuple[bytes, str, str]:
        """Download an application image before uploading it to Telegram."""

        parsed = urlparse(image_url)

        if parsed.scheme not in {"http", "https"}:
            raise TelegramAPIError(
                "Product image URL must use HTTP or HTTPS."
            )

        try:
            response = await self._media_client.get(image_url)
        except httpx.HTTPError as exc:
            raise TelegramAPIError(
                f"Could not download product image: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise TelegramAPIError(
                "Could not download product image from backend: "
                f"HTTP {response.status_code}"
            )

        image_bytes = response.content

        if not image_bytes:
            raise TelegramAPIError(
                "Product image download returned an empty response."
            )

        if len(image_bytes) > _MAX_IMAGE_SIZE:
            raise TelegramAPIError(
                "Product image exceeds the 10 MB upload limit."
            )

        # Prefer the HTTP Content-Type returned by the backend.
        content_type = response.headers.get("content-type", "")

        # Remove parameters such as:
        # image/jpeg; charset=utf-8
        mime_type = content_type.split(";", 1)[0].strip().lower()

        if mime_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            # Fall back to the URL extension.
            guessed_type = mimetypes.guess_type(
                parsed.path
            )[0]

            if guessed_type:
                mime_type = guessed_type.lower()

        if mime_type not in _ALLOWED_IMAGE_CONTENT_TYPES:
            raise TelegramAPIError(
                "Could not determine a supported image MIME type. "
                f"Received: {content_type or 'unknown'}"
            )

        filename = Path(parsed.path).name or "product-image"

        # Ensure the filename has an extension.
        if "." not in filename:
            extension = mimetypes.guess_extension(mime_type) or ".jpg"
            filename = f"{filename}{extension}"

        return image_bytes, mime_type, filename

    # ------------------------------------------------------------------
    # Telegram account
    # ------------------------------------------------------------------

    async def get_me(self) -> dict:
        """Validate the bot token and return Telegram bot information."""

        resp = await self._client.get("/getMe")

        data = _safe_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"getMe failed: {data}"
            )

        return data["result"]

    # ------------------------------------------------------------------
    # webhook
    # ------------------------------------------------------------------

    async def set_webhook(
        self,
        webhook_url: str,
        secret_token: str,
    ) -> None:
        """Register the Telegram webhook."""

        resp = await self._client.post(
            "/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": secret_token,
            },
        )

        data = _safe_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"setWebhook failed: {data}"
            )

    async def delete_webhook(self) -> None:
        """Remove the Telegram webhook."""

        resp = await self._client.post("/deleteWebhook")

        data = _safe_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"deleteWebhook failed: {data}"
            )

    # ------------------------------------------------------------------
    # incoming media
    # ------------------------------------------------------------------

    async def download_media(
        self,
        media_id: str,
    ) -> tuple[bytes, str]:
        """Download Telegram media by file_id.

        Telegram requires two steps:

        1. getFile(file_id)
        2. Download the returned file_path from the Telegram file server.
        """

        meta_resp = await self._client.get(
            "/getFile",
            params={
                "file_id": media_id,
            },
        )

        meta = _safe_json(meta_resp)

        if not meta.get("ok"):
            raise TelegramAPIError(
                f"getFile failed for {media_id}: {meta}"
            )

        result = meta.get("result") or {}
        file_path = result.get("file_path")

        if not file_path:
            raise TelegramAPIError(
                f"Telegram did not return a file_path for {media_id}"
            )

        file_url = (
            f"{TELEGRAM_API_BASE}"
            f"/file/bot{self.bot_token}/{file_path}"
        )

        try:
            file_resp = await self._client.get(file_url)
        except httpx.HTTPError as exc:
            raise TelegramAPIError(
                f"Could not download media {media_id}: {exc}"
            ) from exc

        if file_resp.status_code >= 400:
            raise TelegramAPIError(
                f"Could not download media {media_id}: "
                f"HTTP {file_resp.status_code}"
            )

        extension = (
            "."
            + file_path.rsplit(".", 1)[-1].lower()
            if "." in file_path
            else ""
        )

        mime_type = (
            _EXTENSION_MIME_OVERRIDES.get(extension)
            or mimetypes.guess_type(file_path)[0]
            or file_resp.headers.get("content-type")
            or "application/octet-stream"
        )

        # Remove parameters such as:
        # audio/ogg; charset=utf-8
        mime_type = mime_type.split(";", 1)[0].strip().lower()

        return file_resp.content, mime_type

    # ------------------------------------------------------------------
    # incoming messages
    # ------------------------------------------------------------------

    def parse_incoming(
        self,
        payload: dict,
    ) -> IncomingMessage | None:
        """Convert a Telegram webhook payload into IncomingMessage."""

        message = payload.get("message")

        if message is None:
            # Ignore edited_message, channel_post, callback_query, etc.
            # Those can be added later as separate features.
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})

        external_conversation_id = str(
            chat.get("id")
        )

        external_user_id = (
            str(sender["id"])
            if sender.get("id") is not None
            else None
        )

        external_user_name = (
            sender.get("username")
            or sender.get("first_name")
        )

        external_message_id = (
            str(message["message_id"])
            if message.get("message_id") is not None
            else None
        )

        # --------------------------------------------------------------
        # text
        # --------------------------------------------------------------

        if "text" in message:
            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.TEXT,
                text=message["text"],
                external_message_id=external_message_id,
            )

        # --------------------------------------------------------------
        # photo
        # --------------------------------------------------------------

        if "photo" in message:
            photos = message.get("photo") or []

            if not photos:
                return None

            # Telegram normally orders photo sizes from smallest to
            # largest, so the final item is the largest available.
            largest = photos[-1]

            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.IMAGE,
                text=message.get("caption"),
                external_message_id=external_message_id,
                media_file_id=largest.get("file_id"),
            )

        # --------------------------------------------------------------
        # document
        # --------------------------------------------------------------

        if "document" in message:
            document = message.get("document") or {}

            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.DOCUMENT,
                text=message.get("caption"),
                external_message_id=external_message_id,
                media_file_id=document.get("file_id"),
            )

        # --------------------------------------------------------------
        # voice
        # --------------------------------------------------------------

        if "voice" in message:
            voice = message.get("voice") or {}

            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.VOICE,
                text=None,
                external_message_id=external_message_id,
                media_file_id=voice.get("file_id"),
            )

        # --------------------------------------------------------------
        # location
        # --------------------------------------------------------------

        if "location" in message:
            location = message.get("location") or {}

            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.LOCATION,
                text=None,
                external_message_id=external_message_id,
                latitude=location.get("latitude"),
                longitude=location.get("longitude"),
            )

        # --------------------------------------------------------------
        # unsupported / generic Telegram message
        # --------------------------------------------------------------

        return IncomingMessage(
            external_conversation_id=external_conversation_id,
            external_user_id=external_user_id,
            external_user_name=external_user_name,
            message_type=MessageType.OTHER,
            text=None,
            external_message_id=external_message_id,
        )


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def _safe_json(response: httpx.Response) -> dict:
    """Safely decode a Telegram/backend HTTP response as JSON."""

    try:
        data = response.json()
    except ValueError:
        raise TelegramAPIError(
            f"HTTP {response.status_code} returned invalid JSON: "
            f"{response.text[:500]}"
        )

    if not isinstance(data, dict):
        raise TelegramAPIError(
            f"HTTP {response.status_code} returned unexpected JSON."
        )

    return data


def _split_for_telegram(
    text: str,
    limit: int = 4096,
) -> list[str]:
    """Split text into Telegram-safe message sizes."""

    if len(text) <= limit:
        return [text]

    return [
        text[i : i + limit]
        for i in range(0, len(text), limit)
    ]

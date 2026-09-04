"""Telegram implementation of PlatformAdapter.

Talks to the Telegram Bot API directly over httpx (same approach as
GeminiProvider — one small REST surface, no need for a heavyweight SDK).

Scope note: parse_incoming() recognizes text, photo, document, voice,
and location messages. Photo and voice file_ids are now actually
downloadable via download_media() (see below) and analyzed by
MessagingPipeline — see app/models/message.py's docstring for the
history of that gap and app/services/messaging_pipeline.py for how
the analysis is used.
"""
import mimetypes

import httpx

from app.models.message import MessageType
from app.services.platforms.base import IncomingMessage, PlatformAdapter

TELEGRAM_API_BASE = "https://api.telegram.org"

# Telegram's getFile response gives back a file_path but no mime_type —
# unlike WhatsApp's media API. Voice notes are consistently Opus-in-OGG
# (file_path ends in .oga); everything else we fall back to guessing
# from the extension, then a generic octet-stream if that fails too.
_EXTENSION_MIME_OVERRIDES = {".oga": "audio/ogg", ".ogg": "audio/ogg"}


class TelegramAPIError(Exception):
    pass


class TelegramAdapter(PlatformAdapter):
    platform_name = "telegram"

    def __init__(self, bot_token: str, timeout: float = 15.0):
        self.bot_token = bot_token
        self._client = httpx.AsyncClient(
            base_url=f"{TELEGRAM_API_BASE}/bot{bot_token}", timeout=timeout
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    # ---------- outgoing ----------

    async def send_text(self, external_conversation_id: str, text: str) -> None:
        # Telegram messages are capped at 4096 chars; split rather than truncate/error.
        for part in _split_for_telegram(text):
            resp = await self._client.post(
                "/sendMessage", json={"chat_id": external_conversation_id, "text": part}
            )
            data = resp.json()
            if not data.get("ok"):
                raise TelegramAPIError(f"sendMessage failed: {data}")

    async def send_photo(
        self, external_conversation_id: str, image_url: str, caption: str | None = None
    ) -> None:
        # Telegram captions are capped at 1024 chars; longer text should go
        # in a separate send_text() call rather than truncating silently.
        payload = {"chat_id": external_conversation_id, "photo": image_url}
        if caption:
            payload["caption"] = caption[:1024]
        resp = await self._client.post("/sendPhoto", json=payload)
        data = resp.json()
        if not data.get("ok"):
            raise TelegramAPIError(f"sendPhoto failed: {data}")

    async def get_me(self) -> dict:
        """Used by IntegrationService to validate a bot token and fetch
        the bot's username at connect time."""
        resp = await self._client.get("/getMe")
        data = resp.json()
        if not data.get("ok"):
            raise TelegramAPIError(f"getMe failed: {data}")
        return data["result"]

    async def set_webhook(self, webhook_url: str, secret_token: str) -> None:
        resp = await self._client.post(
            "/setWebhook", json={"url": webhook_url, "secret_token": secret_token}
        )
        data = resp.json()
        if not data.get("ok"):
            raise TelegramAPIError(f"setWebhook failed: {data}")

    async def delete_webhook(self) -> None:
        resp = await self._client.post("/deleteWebhook")
        data = resp.json()
        if not data.get("ok"):
            raise TelegramAPIError(f"deleteWebhook failed: {data}")

    # ---------- media ----------

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Two-step dance, same shape as WhatsApp's: resolve the
        file_id to a file_path via getFile, then fetch the bytes from
        Telegram's separate file-serving host (note: NOT under
        /bot{token}/ like the rest of the API — it's /file/bot{token}/)."""
        meta_resp = await self._client.get("/getFile", params={"file_id": media_id})
        meta = meta_resp.json()
        if not meta.get("ok"):
            raise TelegramAPIError(f"getFile failed for {media_id}: {meta}")

        file_path = meta["result"]["file_path"]
        file_url = f"{TELEGRAM_API_BASE}/file/bot{self.bot_token}/{file_path}"
        file_resp = await self._client.get(file_url)
        if file_resp.status_code >= 400:
            raise TelegramAPIError(f"Could not download media {media_id}: HTTP {file_resp.status_code}")

        extension = "." + file_path.rsplit(".", 1)[-1].lower() if "." in file_path else ""
        mime_type = (
            _EXTENSION_MIME_OVERRIDES.get(extension)
            or mimetypes.guess_type(file_path)[0]
            or file_resp.headers.get("content-type")
            or "application/octet-stream"
        )
        return file_resp.content, mime_type

    # ---------- incoming ----------

    def parse_incoming(self, payload: dict) -> IncomingMessage | None:
        message = payload.get("message")
        if message is None:
            # Ignore edited_message, channel_post, callback_query, etc. for now —
            # each is a real future feature (inline buttons, edit handling), not
            # in scope for this milestone.
            return None

        chat = message.get("chat", {})
        sender = message.get("from", {})
        external_conversation_id = str(chat.get("id"))
        external_user_id = str(sender["id"]) if sender.get("id") is not None else None
        external_user_name = sender.get("username") or sender.get("first_name")
        external_message_id = (
            str(message["message_id"]) if message.get("message_id") is not None else None
        )

        if "text" in message:
            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.TEXT,
                text=message["text"],
                external_message_id=external_message_id,
            )

        if "photo" in message:
            # Telegram sends multiple sizes; the last is the largest.
            largest = message["photo"][-1]
            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.IMAGE,
                text=message.get("caption"),
                external_message_id=external_message_id,
                media_file_id=largest.get("file_id"),
            )

        if "document" in message:
            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.DOCUMENT,
                text=message.get("caption"),
                external_message_id=external_message_id,
                media_file_id=message["document"].get("file_id"),
            )

        if "voice" in message:
            return IncomingMessage(
                external_conversation_id=external_conversation_id,
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.VOICE,
                text=None,
                external_message_id=external_message_id,
                media_file_id=message["voice"].get("file_id"),
            )

        if "location" in message:
            location = message["location"]
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

        # Sticker, poll, contact, etc. — acknowledged generically rather than dropped.
        return IncomingMessage(
            external_conversation_id=external_conversation_id,
            external_user_id=external_user_id,
            external_user_name=external_user_name,
            message_type=MessageType.OTHER,
            text=None,
            external_message_id=external_message_id,
        )


def _split_for_telegram(text: str, limit: int = 4096) -> list[str]:
    if len(text) <= limit:
        return [text]
    return [text[i : i + limit] for i in range(0, len(text), limit)]

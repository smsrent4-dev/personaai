"""Telegram implementation of PlatformAdapter."""

from __future__ import annotations

import json
import mimetypes

import httpx

from app.models.message import MessageType
from app.services.platforms.base import IncomingMessage, PlatformAdapter

TELEGRAM_API_BASE = "https://api.telegram.org"

_EXTENSION_MIME_OVERRIDES = {
    ".oga": "audio/ogg",
    ".ogg": "audio/ogg",
}


class TelegramAPIError(Exception):
    """Raised when the Telegram Bot API returns an error."""


class TelegramAdapter(PlatformAdapter):
    platform_name = "telegram"

    def __init__(
        self,
        bot_token: str,
        timeout: float = 15.0,
    ):
        self.bot_token = bot_token
        self._client = httpx.AsyncClient(
            base_url=f"{TELEGRAM_API_BASE}/bot{bot_token}",
            timeout=timeout,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def send_text(
        self,
        external_conversation_id: str,
        text: str,
    ) -> None:
        for part in _split_for_telegram(text):
            resp = await self._client.post(
                "/sendMessage",
                json={
                    "chat_id": external_conversation_id,
                    "text": part,
                },
            )

            data = _response_json(resp)

            if not data.get("ok"):
                raise TelegramAPIError(
                    f"sendMessage failed: {data}"
                )

    async def send_photo(
        self,
        external_conversation_id: str,
        image_url: str,
        caption: str | None = None,
    ) -> None:
        payload = {
            "chat_id": external_conversation_id,
            "photo": image_url,
        }

        if caption:
            payload["caption"] = caption[:1024]

        resp = await self._client.post(
            "/sendPhoto",
            json=payload,
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"sendPhoto failed: {data}"
            )

    async def get_me(self) -> dict:
        resp = await self._client.get("/getMe")

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"getMe failed: {data}"
            )

        return data["result"]

    async def get_business_connection(
        self,
        business_connection_id: str,
    ) -> dict:
        business_connection_id = (
            business_connection_id.strip()
        )

        if not business_connection_id:
            raise TelegramAPIError(
                "business_connection_id is required"
            )

        resp = await self._client.get(
            "/getBusinessConnection",
            params={
                "business_connection_id": (
                    business_connection_id
                ),
            },
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"getBusinessConnection failed: {data}"
            )

        return data["result"]

    async def post_story(
        self,
        business_connection_id: str,
        content: dict,
        active_period: int = 86400,
        caption: str | None = None,
        parse_mode: str | None = None,
        post_to_chat_page: bool = False,
        protect_content: bool = False,
    ) -> dict:
        """Publish a Telegram Business Story using an existing content reference.

        This method is useful when the Telegram API can resolve the supplied
        InputStoryContent directly. For newly uploaded media, use
        post_story_media().
        """

        business_connection_id = (
            business_connection_id.strip()
        )

        if not business_connection_id:
            raise TelegramAPIError(
                "business_connection_id is required"
            )

        if not isinstance(content, dict) or not content:
            raise TelegramAPIError(
                "Story content is required"
            )

        _validate_story_active_period(active_period)

        payload: dict = {
            "business_connection_id": (
                business_connection_id
            ),
            "content": content,
            "active_period": active_period,
            "post_to_chat_page": post_to_chat_page,
            "protect_content": protect_content,
        }

        if caption:
            payload["caption"] = caption[:2048]

        if parse_mode:
            payload["parse_mode"] = parse_mode

        resp = await self._client.post(
            "/postStory",
            json=payload,
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"postStory failed: {data}"
            )

        return data["result"]

    async def post_story_media(
        self,
        business_connection_id: str,
        media_bytes: bytes,
        filename: str,
        mime_type: str,
        media_type: str,
        active_period: int = 86400,
        caption: str | None = None,
        parse_mode: str | None = None,
        post_to_chat_page: bool = False,
        protect_content: bool = False,
    ) -> dict:
        """Upload media and publish it as a Telegram Business Story.

        Telegram Story media must be uploaded as a new file and referenced
        from InputStoryContent using attach://<filename>.
        """

        business_connection_id = (
            business_connection_id.strip()
        )

        if not business_connection_id:
            raise TelegramAPIError(
                "business_connection_id is required"
            )

        if not media_bytes:
            raise TelegramAPIError(
                "Story media is empty"
            )

        media_type = media_type.strip().lower()

        if media_type not in {
            "image",
            "video",
        }:
            raise TelegramAPIError(
                "Story media_type must be image or video"
            )

        if not filename:
            filename = (
                "story.jpg"
                if media_type == "image"
                else "story.mp4"
            )

        mime_type = (
            mime_type.strip().lower()
            if mime_type
            else (
                "image/jpeg"
                if media_type == "image"
                else "video/mp4"
            )
        )

        expected_prefix = (
            "image/"
            if media_type == "image"
            else "video/"
        )

        if not mime_type.startswith(expected_prefix):
            raise TelegramAPIError(
                f"Invalid MIME type {mime_type!r} "
                f"for {media_type} Story"
            )

        _validate_story_active_period(active_period)

        content = {
            "type": (
                "photo"
                if media_type == "image"
                else "video"
            ),
        }

        if media_type == "image":
            content["photo"] = f"attach://{filename}"
        else:
            content["video"] = f"attach://{filename}"

        form_data: dict[str, str] = {
            "business_connection_id": (
                business_connection_id
            ),
            "content": json.dumps(
                content,
                separators=(",", ":"),
            ),
            "active_period": str(active_period),
            "post_to_chat_page": str(
                post_to_chat_page
            ).lower(),
            "protect_content": str(
                protect_content
            ).lower(),
        }

        if caption:
            form_data["caption"] = caption[:2048]

        if parse_mode:
            form_data["parse_mode"] = parse_mode

        resp = await self._client.post(
            "/postStory",
            data=form_data,
            files={
                "photo" if media_type == "image" else "video": (
                    filename,
                    media_bytes,
                    mime_type,
                )
            },
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"postStory failed: {data}"
            )

        return data["result"]

    async def edit_story(
        self,
        business_connection_id: str,
        story_id: int,
        content: dict | None = None,
        caption: str | None = None,
        parse_mode: str | None = None,
        areas: list[dict] | None = None,
    ) -> dict:
        business_connection_id = (
            business_connection_id.strip()
        )

        if not business_connection_id:
            raise TelegramAPIError(
                "business_connection_id is required"
            )

        payload: dict = {
            "business_connection_id": (
                business_connection_id
            ),
            "story_id": story_id,
        }

        if content is not None:
            payload["content"] = content

        if caption is not None:
            payload["caption"] = caption[:2048]

        if parse_mode:
            payload["parse_mode"] = parse_mode

        if areas is not None:
            payload["areas"] = areas

        resp = await self._client.post(
            "/editStory",
            json=payload,
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"editStory failed: {data}"
            )

        return data["result"]

    async def delete_story(
        self,
        business_connection_id: str,
        story_id: int,
    ) -> bool:
        business_connection_id = (
            business_connection_id.strip()
        )

        if not business_connection_id:
            raise TelegramAPIError(
                "business_connection_id is required"
            )

        resp = await self._client.post(
            "/deleteStory",
            json={
                "business_connection_id": (
                    business_connection_id
                ),
                "story_id": story_id,
            },
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"deleteStory failed: {data}"
            )

        return bool(data["result"])

    async def set_webhook(
        self,
        webhook_url: str,
        secret_token: str,
    ) -> None:
        resp = await self._client.post(
            "/setWebhook",
            json={
                "url": webhook_url,
                "secret_token": secret_token,
            },
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"setWebhook failed: {data}"
            )

    async def delete_webhook(self) -> None:
        resp = await self._client.post(
            "/deleteWebhook"
        )

        data = _response_json(resp)

        if not data.get("ok"):
            raise TelegramAPIError(
                f"deleteWebhook failed: {data}"
            )

    async def download_media(
        self,
        media_id: str,
    ) -> tuple[bytes, str]:
        media_id = media_id.strip()

        if not media_id:
            raise TelegramAPIError(
                "media_id is required"
            )

        meta_resp = await self._client.get(
            "/getFile",
            params={
                "file_id": media_id,
            },
        )

        meta = _response_json(meta_resp)

        if not meta.get("ok"):
            raise TelegramAPIError(
                f"getFile failed for {media_id}: {meta}"
            )

        result = meta.get("result") or {}
        file_path = result.get("file_path")

        if not file_path:
            raise TelegramAPIError(
                f"Telegram returned no file_path for {media_id}"
            )

        file_url = (
            f"{TELEGRAM_API_BASE}/file/"
            f"bot{self.bot_token}/{file_path}"
        )

        file_resp = await self._client.get(file_url)

        if file_resp.status_code >= 400:
            raise TelegramAPIError(
                "Could not download media "
                f"{media_id}: HTTP {file_resp.status_code}"
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

        return file_resp.content, mime_type

    def parse_incoming(
        self,
        payload: dict,
    ) -> IncomingMessage | None:
        message = payload.get("message")

        if message is None:
            return None

        chat = message.get("chat") or {}
        sender = message.get("from") or {}

        chat_id = chat.get("id")

        if chat_id is None:
            return None

        external_conversation_id = str(chat_id)

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

        if "text" in message:
            return IncomingMessage(
                external_conversation_id=(
                    external_conversation_id
                ),
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.TEXT,
                text=message["text"],
                external_message_id=external_message_id,
            )

        if "photo" in message:
            photos = message.get("photo") or []

            if photos:
                largest = photos[-1]

                return IncomingMessage(
                    external_conversation_id=(
                        external_conversation_id
                    ),
                    external_user_id=external_user_id,
                    external_user_name=external_user_name,
                    message_type=MessageType.IMAGE,
                    text=message.get("caption"),
                    external_message_id=(
                        external_message_id
                    ),
                    media_file_id=largest.get("file_id"),
                )

        if "document" in message:
            document = message.get("document") or {}

            return IncomingMessage(
                external_conversation_id=(
                    external_conversation_id
                ),
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.DOCUMENT,
                text=message.get("caption"),
                external_message_id=external_message_id,
                media_file_id=document.get("file_id"),
            )

        if "voice" in message:
            voice = message.get("voice") or {}

            return IncomingMessage(
                external_conversation_id=(
                    external_conversation_id
                ),
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.VOICE,
                text=None,
                external_message_id=external_message_id,
                media_file_id=voice.get("file_id"),
            )

        if "location" in message:
            location = message.get("location") or {}

            return IncomingMessage(
                external_conversation_id=(
                    external_conversation_id
                ),
                external_user_id=external_user_id,
                external_user_name=external_user_name,
                message_type=MessageType.LOCATION,
                text=None,
                external_message_id=external_message_id,
                latitude=location.get("latitude"),
                longitude=location.get("longitude"),
            )

        return IncomingMessage(
            external_conversation_id=(
                external_conversation_id
            ),
            external_user_id=external_user_id,
            external_user_name=external_user_name,
            message_type=MessageType.OTHER,
            text=None,
            external_message_id=external_message_id,
        )


def _response_json(
    response: httpx.Response,
) -> dict:
    try:
        data = response.json()
    except ValueError as exc:
        raise TelegramAPIError(
            "Telegram returned an invalid JSON response: "
            f"HTTP {response.status_code}"
        ) from exc

    if not isinstance(data, dict):
        raise TelegramAPIError(
            "Telegram returned an unexpected response format"
        )

    return data


def _validate_story_active_period(
    active_period: int,
) -> None:
    if active_period not in {
        21600,
        43200,
        86400,
        172800,
    }:
        raise TelegramAPIError(
            "active_period must be 21600, 43200, "
            "86400, or 172800 seconds"
        )


def _split_for_telegram(
    text: str,
    limit: int = 4096,
) -> list[str]:
    if len(text) <= limit:
        return [text]

    return [
        text[i : i + limit]
        for i in range(0, len(text), limit)
    ]
"""PlatformAdapter — the interface every messaging platform implements.

Same pattern as AIProvider (app/services/ai/base.py): nothing above
this layer (the messaging pipeline, webhook endpoints) is allowed to
know it's talking to Telegram specifically. Adding WhatsApp/Discord/
Instagram/Messenger/Slack/a web chat widget later means implementing
this interface in a new file and registering it in
app/services/platforms/registry.py — nothing else changes.

Unlike AIProvider (one instance per provider, shared across all
users), a PlatformAdapter instance is per-integration, since each
user's bot has its own token/credentials. See registry.py.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.models.message import MessageType


@dataclass
class IncomingMessage:
    """Normalized shape every adapter's parse_incoming() returns,
    regardless of the platform's actual webhook payload format."""

    external_conversation_id: str
    external_user_id: str | None
    external_user_name: str | None
    message_type: MessageType
    text: str | None                 # message text, or a caption for media
    external_message_id: str | None = None
    media_file_id: str | None = None  # platform-specific file reference (e.g. Telegram file_id)
    latitude: float | None = None
    longitude: float | None = None
    # Structured extras that don't fit the fields above — e.g. WhatsApp's
    # shared contact card, or which interactive button/list option a
    # customer picked. Stored as-is on Message.platform_metadata.
    platform_metadata: dict | None = None


class PlatformAdapter(ABC):
    platform_name: str = "base"

    @abstractmethod
    def parse_incoming(self, payload: dict) -> IncomingMessage | None:
        """Normalizes a raw webhook payload. Returns None for payload
        types this adapter deliberately ignores (e.g. Telegram's
        edited_message or channel_post updates, in this milestone)."""
        raise NotImplementedError

    @abstractmethod
    async def send_text(self, external_conversation_id: str, text: str) -> None:
        raise NotImplementedError

    async def send_photo(
        self, external_conversation_id: str, image_url: str, caption: str | None = None
    ) -> None:
        """Default: not every platform will support this on day one, so
        adapters that don't implement it yet fall back to a text-only
        mention rather than crashing. TelegramAdapter overrides this with
        a real sendPhoto call."""
        text = caption or "[image]"
        await self.send_text(external_conversation_id, text)

    # ---------- rich media / status (added for WhatsApp, Milestone 8) ----------
    # Every method below has a safe default (usually "fall back to a text
    # mention", same spirit as send_photo above) so existing adapters
    # (Telegram) keep working unmodified — implementing these is opt-in per
    # platform, not a breaking interface change.

    async def send_image(self, external_conversation_id: str, image_url: str, caption: str | None = None) -> None:
        await self.send_photo(external_conversation_id, image_url, caption)

    async def send_document(
        self, external_conversation_id: str, document_url: str, filename: str | None = None, caption: str | None = None
    ) -> None:
        await self.send_text(external_conversation_id, caption or f"[document: {filename or document_url}]")

    async def send_audio(self, external_conversation_id: str, audio_url: str) -> None:
        await self.send_text(external_conversation_id, "[audio message]")

    async def send_video(self, external_conversation_id: str, video_url: str, caption: str | None = None) -> None:
        await self.send_text(external_conversation_id, caption or "[video]")

    async def send_location(
        self, external_conversation_id: str, latitude: float, longitude: float, name: str | None = None
    ) -> None:
        await self.send_text(external_conversation_id, f"[location: {name or f'{latitude}, {longitude}'}]")

    async def send_contact(self, external_conversation_id: str, name: str, phone: str) -> None:
        await self.send_text(external_conversation_id, f"[contact: {name} — {phone}]")

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        """Returns (raw_bytes, mime_type) for a platform-native media
        reference. Not every adapter can support this without extra
        credentials context; default raises so callers get a clear error
        instead of silently returning empty bytes."""
        raise NotImplementedError(f"{self.platform_name} adapter does not support download_media()")

    async def mark_read(self, external_message_id: str, show_typing: bool = False) -> None:
        """Marks an inbound message as read, optionally with a typing
        indicator. No-op by default — read receipts/typing indicators are
        a platform-level nicety, not required for the pipeline to function."""
        return None

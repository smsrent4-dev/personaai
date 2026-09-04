"""Message model.

`role` distinguishes who said it. `message_type` beyond TEXT is stored
with a platform file reference (`media_file_id`). IMAGE and VOICE
messages are downloaded and actually analyzed (vision description /
transcription) by MessagingPipeline — see its module docstring — with
the result backfilled into this row's `content` via
ConversationService.update_message_content so conversation history
reflects what the media actually contained, not just its file
reference. DOCUMENT/VIDEO/LOCATION/CONTACT/OTHER remain a real,
intentional scope boundary for now: the pipeline replies using the
caption/text when present and a generic acknowledgement otherwise.
"""
import enum
import uuid

from sqlalchemy import Enum, Float, ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class MessageRole(str, enum.Enum):
    USER = "user"          # the end customer, on whatever platform
    AGENT = "agent"         # one of the owner's AI agents replied
    SYSTEM = "system"        # e.g. "Routed to Sales Agent", "Human took over"


class MessageType(str, enum.Enum):
    TEXT = "text"
    IMAGE = "image"
    DOCUMENT = "document"
    VOICE = "voice"
    LOCATION = "location"
    VIDEO = "video"        # added for WhatsApp (Milestone 8) — Telegram has no distinct video message type yet
    CONTACT = "contact"    # added for WhatsApp (Milestone 8) — a shared contact card
    OTHER = "other"


class Message(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "messages"

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True
    )

    role: Mapped[MessageRole] = mapped_column(Enum(MessageRole, name="message_role", values_callable=lambda x: [e.value for e in x]), nullable=False)
    message_type: Mapped[MessageType] = mapped_column(
        Enum(MessageType, name="message_type", values_callable=lambda x: [e.value for e in x]), default=MessageType.TEXT, nullable=False
    )
    content: Mapped[str | None] = mapped_column(Text, nullable=True)

    external_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    media_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)
    latitude: Mapped[float | None] = mapped_column(Float, nullable=True)
    longitude: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Structured platform-specific extras that don't fit `content`/media
    # fields — e.g. a WhatsApp shared contact card ({"name": ..., "phone": ...})
    # or which button/list option a customer picked. Nullable, empty for
    # every message type that doesn't need it (i.e. everything pre-WhatsApp).
    platform_metadata: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")

    def __repr__(self) -> str:
        preview = (self.content or f"<{self.message_type.value}>")[:40]
        return f"<Message {self.role.value}: {preview!r}>"

"""Conversation model.

One Conversation per (owner, platform, external_conversation_id) —
e.g. one row per Telegram chat. `agent_id` tracks whichever agent most
recently answered (the Router can pick a different agent per message,
so this is "current handler", not a permanent assignment).
"""
import enum
import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, JSON, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.platform_enums import Platform

if TYPE_CHECKING:
    from app.models.message import Message


class ConversationStatus(str, enum.Enum):
    OPEN = "open"
    CLOSED = "closed"


class Conversation(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint(
            "owner_id", "platform", "external_conversation_id", name="uq_conversation_identity"
        ),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="SET NULL"), nullable=True, index=True
    )

    platform: Mapped[Platform] = mapped_column(Enum(Platform, name="conversation_platform", values_callable=lambda x: [e.value for e in x]), nullable=False)
    external_conversation_id: Mapped[str] = mapped_column(String(255), nullable=False)
    external_user_id: Mapped[str | None] = mapped_column(String(255), nullable=True)
    external_user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[ConversationStatus] = mapped_column(
        Enum(ConversationStatus, name="conversation_status", values_callable=lambda x: [e.value for e in x]), default=ConversationStatus.OPEN, nullable=False
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # ["billing", "vip"] — free-form labels for filtering in the Conversation Viewer
    tags: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    # When true, MessagingPipeline stores incoming messages but does NOT
    # generate/send an AI reply — a human is handling this thread instead.
    assigned_to_human: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    messages: Mapped[list["Message"]] = relationship(
        "Message", back_populates="conversation", cascade="all, delete-orphan", order_by="Message.created_at"
    )

    def __repr__(self) -> str:
        return f"<Conversation {self.platform.value}:{self.external_conversation_id}>"

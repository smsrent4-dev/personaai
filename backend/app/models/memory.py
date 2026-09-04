"""Memory model.

`agent_id` nullable means the memory applies across every agent the
user owns (e.g. "my office is now in Lagos" is true regardless of
which agent answers). A non-null `agent_id` scopes it to one agent
(e.g. "never mention Flutter" said while editing the Sales Agent).
"""
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Enum, ForeignKey, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.core.types import GUID, Embedding
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    pass


class MemoryType(str, enum.Enum):
    FACT = "fact"
    PREFERENCE = "preference"
    EVENT = "event"
    CONVERSATION_SUMMARY = "conversation_summary"


class MemorySource(str, enum.Enum):
    TEACH = "teach"            # entered via "Teach My AI"
    CONVERSATION = "conversation"  # distilled from a conversation (Milestone 5+)
    MANUAL = "manual"          # created directly via the Memory API/page


class MemoryEntry(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "memory_entries"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("agents.id", ondelete="CASCADE"), nullable=True, index=True
    )

    memory_type: Mapped[MemoryType] = mapped_column(Enum(MemoryType, name="memory_type", values_callable=lambda x: [e.value for e in x]), nullable=False)
    source: Mapped[MemorySource] = mapped_column(
        Enum(MemorySource, name="memory_source", values_callable=lambda x: [e.value for e in x]), default=MemorySource.MANUAL, nullable=False
    )
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Embedding(settings.EMBEDDING_DIMENSIONS), nullable=False)

    def __repr__(self) -> str:
        return f"<MemoryEntry {self.memory_type.value}: {self.content[:40]!r}>"

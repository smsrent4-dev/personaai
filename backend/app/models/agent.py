"""Agent model.

Table shape only in Milestone 1 — the Router, memory wiring, and
knowledge-source linking land in Milestone 3/4. Defined now because
User.agents relationship needs the target table to exist for Alembic
to generate a correct initial migration.
"""
import enum
import uuid
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Enum, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.user import User


class AgentType(str, enum.Enum):
    PERSONAL = "personal"
    SALES = "sales"
    SUPPORT = "support"
    OPPORTUNITY = "opportunity"
    CUSTOM = "custom"


class AgentStatus(str, enum.Enum):
    ACTIVE = "active"
    PAUSED = "paused"
    DRAFT = "draft"


class Agent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "agents"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    avatar_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    agent_type: Mapped[AgentType] = mapped_column(
        Enum(
            AgentType,
            name="agent_type",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        nullable=False,
    )

    instructions: Mapped[str] = mapped_column(Text, default="", nullable=False)
    model: Mapped[str] = mapped_column(String(128), default="gemini-2.0-flash", nullable=False)
    temperature: Mapped[float] = mapped_column(Float, default=0.7, nullable=False)

    # Free-form permission flags, e.g. {"can_access_products": true, "can_create_quotes": true}
    permissions: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[AgentStatus] = mapped_column(
        Enum(
            AgentStatus,
            name="agent_status",
            values_callable=lambda enum: [e.value for e in enum],
        ),
        default=AgentStatus.DRAFT,
        nullable=False,
    )

    owner: Mapped["User"] = relationship("User", back_populates="agents")

    def __repr__(self) -> str:
        return f"<Agent {self.name} ({self.agent_type.value})>"

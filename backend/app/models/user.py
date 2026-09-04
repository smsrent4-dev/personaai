"""User account model — the tenant root. Every piece of data in the
platform (agents, knowledge, conversations, products) hangs off a
User via a foreign key, which is how multi-tenant isolation is enforced
at the query layer (see app/core/deps.py::get_current_user usage in
every repository/service method)."""
import enum
import uuid
from typing import List, TYPE_CHECKING

from sqlalchemy import Boolean, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin

if TYPE_CHECKING:
    from app.models.agent import Agent


class UserRole(str, enum.Enum):
    OWNER = "owner"          # owns the tenant account
    ADMIN = "admin"          # full access within the tenant
    MEMBER = "member"        # limited access (e.g. conversation viewer only)


class User(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)

    role: Mapped[UserRole] = mapped_column(
        Enum(UserRole, name="user_role", values_callable=lambda x: [e.value for e in x]), default=UserRole.OWNER, nullable=False
    )

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    # Distinct from the per-account `role` above (owner/admin/member within
    # ONE business's account). This flags someone who operates PersonaAI
    # itself and can see/manage every customer's account. See
    # app/api/v1/endpoints/admin.py and app/core/deps.py::require_platform_admin.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Business/persona context used by the Personal Agent (Milestone 3+)
    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    timezone: Mapped[str] = mapped_column(String(64), default="UTC", nullable=False)

    agents: Mapped[List["Agent"]] = relationship(
        "Agent", back_populates="owner", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:
        return f"<User {self.email} ({self.role.value})>"

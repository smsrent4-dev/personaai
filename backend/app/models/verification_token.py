"""Single-use tokens for email verification and password-reset flows.

Both flows share the same shape (a random token, an expiry, a
used flag), so they share one table distinguished by `purpose`
rather than duplicating two near-identical models.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class TokenPurpose(str, enum.Enum):
    EMAIL_VERIFICATION = "email_verification"
    PASSWORD_RESET = "password_reset"


class VerificationToken(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "verification_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    token_hash: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    purpose: Mapped[TokenPurpose] = mapped_column(Enum(TokenPurpose, name="token_purpose", values_callable=lambda x: [e.value for e in x]), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

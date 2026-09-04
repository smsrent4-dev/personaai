"""A connected messaging platform for one user (e.g. their Telegram bot).

`webhook_secret` is what makes multi-tenant webhooks work: Telegram (and
every other platform) calls back to a URL you registered, and that URL
must somehow tell us *which user's* bot sent the message. Rather than
put the user's ID in the URL (guessable, and leaks account structure),
each integration gets a random secret and the webhook path is
`/telegram/webhook/{webhook_secret}` — see
app/api/v1/endpoints/telegram_webhook.py.

`credentials_encrypted` holds platform-specific secrets (bot_token for
Telegram), encrypted at rest via app/core/crypto.py — see
get_credentials()/set_credentials() below.
"""
import enum
import secrets
import uuid

from sqlalchemy import Boolean, Enum, ForeignKey, JSON, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import decrypt_json, encrypt_json
from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.platform_enums import Platform


class IntegrationStatus(str, enum.Enum):
    ACTIVE = "active"
    DISABLED = "disabled"
    ERROR = "error"  # e.g. Telegram rejected the token or webhook registration failed


def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)


class PlatformIntegration(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "platform_integrations"
    __table_args__ = (UniqueConstraint("owner_id", "platform", name="uq_integration_owner_platform"),)

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform, name="platform", values_callable=lambda x: [e.value for e in x]), nullable=False)

    # Encrypted at rest — see app/core/crypto.py. Never access this column
    # directly; use get_credentials()/set_credentials() below, which every
    # call site (IntegrationService, the adapter registry, HumanReplyService)
    # goes through.
    credentials_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)
    webhook_secret: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, default=generate_webhook_secret, nullable=False
    )

    external_bot_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    external_bot_username: Mapped[str | None] = mapped_column(String(255), nullable=True)

    status: Mapped[IntegrationStatus] = mapped_column(
        Enum(IntegrationStatus, name="integration_status", values_callable=lambda x: [e.value for e in x]), default=IntegrationStatus.ACTIVE, nullable=False
    )
    error_message: Mapped[str | None] = mapped_column(String(1000), nullable=True)

    # Per-integration behavior toggles, generic across platforms rather than
    # one column per setting per platform: {"auto_reply": true,
    # "business_hours": {...}, "typing_indicator": true, "read_receipts": true,
    # "default_agent_id": "...", "human_takeover": false}. Added for
    # WhatsApp's Settings screen (Milestone 8) but usable by any platform.
    settings: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

    def get_credentials(self) -> dict:
        return decrypt_json(self.credentials_encrypted)

    def set_credentials(self, data: dict) -> None:
        self.credentials_encrypted = encrypt_json(data)

    def __repr__(self) -> str:
        return f"<PlatformIntegration {self.platform.value} owner={self.owner_id}>"

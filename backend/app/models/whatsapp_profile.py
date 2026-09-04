"""WhatsAppBusinessProfile — the WhatsApp-specific business metadata that
doesn't belong on the generic `PlatformIntegration` row.

`PlatformIntegration` (app/models/integration.py) already covers what's
common to every platform: encrypted credentials, status, webhook
identity. This table is a 1:1 extension of it, holding only the fields
that are genuinely WhatsApp-specific (quality rating, messaging tier,
the WABA/phone-number IDs, business display info) — the same "extend,
don't duplicate" relationship OrderEvent has to Order.

Sensitive values (access token, verify token) are NOT stored here —
they live in `PlatformIntegration.credentials_encrypted`, same as
Telegram's bot_token, via the existing `get_credentials()`/
`set_credentials()` encryption helpers.
"""
import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class WhatsAppBusinessProfile(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "whatsapp_business_profiles"

    integration_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("platform_integrations.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )

    whatsapp_business_account_id: Mapped[str] = mapped_column(String(64), nullable=False)
    phone_number_id: Mapped[str] = mapped_column(String(64), nullable=False)

    business_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    display_phone_number: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Meta's own health signals for the number — surfaced as-is, not
    # recomputed. GREEN/YELLOW/RED and a messaging tier (e.g. "TIER_1K").
    quality_rating: Mapped[str | None] = mapped_column(String(16), nullable=True)
    messaging_tier: Mapped[str | None] = mapped_column(String(32), nullable=True)

    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)
    updated_by: Mapped[uuid.UUID | None] = mapped_column(GUID(), ForeignKey("users.id"), nullable=True)

    def __repr__(self) -> str:
        return f"<WhatsAppBusinessProfile {self.display_phone_number} integration={self.integration_id}>"

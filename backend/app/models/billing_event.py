"""BillingEvent - one row per Paystack webhook delivery.

Stored regardless of whether we recognize/handle the event type, so
nothing is silently dropped - an event PersonaAI doesn't yet act on
(`processed=False`) is still visible for debugging rather than lost.
"""
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BillingEvent(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "billing_events"

    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    event_type: Mapped[str] = mapped_column(String(100), nullable=False)
    paystack_reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    amount: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    raw_payload: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

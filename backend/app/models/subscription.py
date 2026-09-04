"""Subscription - one row per user (unique on owner_id), tracking their
relationship to a BillingPlan and to Paystack.

`paystack_authorization_encrypted` holds the card authorization Paystack
returns after a successful charge (needed for some recurring-billing
operations) - encrypted at rest via app/core/crypto.py, same pattern
as PlatformIntegration's bot tokens. Never store this in plaintext.
"""
import enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.crypto import decrypt_json, encrypt_json
from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class SubscriptionStatus(str, enum.Enum):
    INCOMPLETE = "incomplete"
    ACTIVE = "active"
    PAST_DUE = "past_due"
    CANCELED = "canceled"


class Subscription(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "subscriptions"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), unique=True, nullable=False, index=True
    )
    plan_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("billing_plans.id", ondelete="SET NULL"), nullable=True, index=True
    )

    status: Mapped[SubscriptionStatus] = mapped_column(
        Enum(SubscriptionStatus, name="subscription_status", values_callable=lambda x: [e.value for e in x]), default=SubscriptionStatus.INCOMPLETE, nullable=False
    )

    paystack_customer_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paystack_subscription_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    paystack_authorization_encrypted: Mapped[str] = mapped_column(Text, default="", nullable=False)

    current_period_end: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def get_authorization(self) -> dict:
        return decrypt_json(self.paystack_authorization_encrypted)

    def set_authorization(self, data: dict) -> None:
        self.paystack_authorization_encrypted = encrypt_json(data)

    def __repr__(self) -> str:
        return f"<Subscription owner={self.owner_id} status={self.status.value}>"

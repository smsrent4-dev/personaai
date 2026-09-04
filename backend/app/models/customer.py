"""Customer model.

Distinct from User (the business owner). A Customer is the owner's
END customer - identified by (owner_id, platform, external_user_id),
same identity pattern as Conversation. get_or_create_customer in
CustomerService resolves this the same way ConversationService does
for threads, so the same person messaging twice is the same Customer
row, not a duplicate.

This is the "Customer Memory" from the spec: purchase history,
preferences, lifetime spend - accumulated automatically as orders are
placed and preferences are learned, not manually entered by the owner.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin
from app.models.platform_enums import Platform


class Customer(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "customers"
    __table_args__ = (
        UniqueConstraint("owner_id", "platform", "external_user_id", name="uq_customer_identity"),
    )

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[Platform] = mapped_column(Enum(Platform, name="customer_platform", values_callable=lambda x: [e.value for e in x]), nullable=False)
    external_user_id: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    lifetime_spend: Mapped[Decimal] = mapped_column(Numeric(12, 2), default=Decimal("0"), nullable=False)
    order_count: Mapped[int] = mapped_column(default=0, nullable=False)
    last_interaction_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    preferred_language: Mapped[str | None] = mapped_column(String(10), nullable=True)
    preferred_payment_method: Mapped[str | None] = mapped_column(String(50), nullable=True)

    interests: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    def __repr__(self) -> str:
        return f"<Customer {self.platform.value}:{self.external_user_id} owner={self.owner_id}>"

"""Notification model.

Delivered via polling (GET /notifications), not a websocket/push
channel - that's a deliberate scope boundary, not a claim of true
real-time delivery. See NotificationService for what triggers each type.
"""
import enum
import uuid

from sqlalchemy import JSON, Boolean, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class NotificationType(str, enum.Enum):
    NEW_LEAD = "new_lead"
    KNOWLEDGE_FAILED = "knowledge_failed"
    INTEGRATION_ERROR = "integration_error"
    PAYMENT_RECEIVED = "payment_received"
    PAYMENT_FAILED = "payment_failed"
    SUBSCRIPTION_CANCELED = "subscription_canceled"
    NEW_ORDER = "new_order"
    PAYMENT_RECEIPT_UPLOADED = "payment_receipt_uploaded"
    ORDER_PAYMENT_CONFIRMED = "order_payment_confirmed"
    PLAN_LIMIT_REACHED = "plan_limit_reached"


class Notification(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "notifications"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[NotificationType] = mapped_column(Enum(NotificationType, name="notification_type", values_callable=lambda x: [e.value for e in x]), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    body: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    context: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)

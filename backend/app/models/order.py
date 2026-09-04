"""Order model.

`items` is a denormalized snapshot ([{product_id, name, quantity,
unit_price, subtotal}]) taken at order-creation time - deliberately
NOT a live join to Product, since a product's price can change after
the order was placed and an order should reflect what was actually
agreed, not today's price.

Three independent status axes (order/payment/delivery) rather than one
combined status, because they genuinely vary independently - an order
can be CONFIRMED with payment still PENDING and delivery NOT_STARTED.
"""
import enum
import uuid
from decimal import Decimal

from sqlalchemy import JSON, Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.types import GUID
from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class OrderStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    PREPARING = "preparing"
    READY = "ready"
    DELIVERED = "delivered"
    CANCELLED = "cancelled"
    REFUNDED = "refunded"


class PaymentStatus(str, enum.Enum):
    UNPAID = "unpaid"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    AWAITING_DELIVERY_PAYMENT = "awaiting_delivery_payment"
    AWAITING_CASH_PAYMENT = "awaiting_cash_payment"
    PAID = "paid"
    REFUNDED = "refunded"


class DeliveryStatus(str, enum.Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    DELIVERED = "delivered"
    NOT_APPLICABLE = "not_applicable"


class Order(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "orders"

    owner_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    customer_id: Mapped[uuid.UUID] = mapped_column(
        GUID(), ForeignKey("customers.id", ondelete="CASCADE"), nullable=False, index=True
    )
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True
    )
    payment_method_id: Mapped[uuid.UUID | None] = mapped_column(
        GUID(), ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True
    )

    items: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="USD", nullable=False)

    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", values_callable=lambda x: [e.value for e in x]), default=OrderStatus.PENDING, nullable=False
    )
    payment_status: Mapped[PaymentStatus] = mapped_column(
        Enum(PaymentStatus, name="order_payment_status", values_callable=lambda x: [e.value for e in x]), default=PaymentStatus.UNPAID, nullable=False
    )
    delivery_status: Mapped[DeliveryStatus] = mapped_column(
        Enum(DeliveryStatus, name="order_delivery_status", values_callable=lambda x: [e.value for e in x]), default=DeliveryStatus.NOT_STARTED, nullable=False
    )

    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    receipt_file_id: Mapped[str | None] = mapped_column(String(500), nullable=True)

    # Delivery details — nullable because a digital/service order never
    # needs them, but see OrderService.create_order and
    # app/services/tools/create_order_tool.py: an order containing any
    # PHYSICAL product is refused (both at the API layer and — the part
    # that actually matters day to day — the AI's create_order tool)
    # until at least recipient_name + shipping_address are provided.
    # Previously nothing on this model captured a delivery address at
    # all, so an AI-created order for a physical product had no
    # structured way to say where it was going.
    recipient_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    recipient_phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    shipping_address: Mapped[str | None] = mapped_column(Text, nullable=True)

    def __repr__(self) -> str:
        return f"<Order {self.id} {self.status.value}/{self.payment_status.value} {self.total_amount} {self.currency}>"

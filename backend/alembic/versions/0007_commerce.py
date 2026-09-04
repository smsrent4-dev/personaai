"""customers, payment_methods, orders, order_events

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-01

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    customer_platform = postgresql.ENUM(
        "telegram", "whatsapp", "discord", "instagram", "messenger", "slack", "web_widget", "voice",
        name="customer_platform",
        create_type=False,
    )
    payment_method_type = postgresql.ENUM("bank_transfer", "cash", "pay_on_delivery", name="payment_method_type", create_type=False)
    order_status = postgresql.ENUM(
        "pending", "confirmed", "preparing", "ready", "delivered", "cancelled", "refunded", name="order_status",
        create_type=False,
    )
    order_payment_status = postgresql.ENUM(
        "unpaid", "awaiting_confirmation", "awaiting_delivery_payment", "awaiting_cash_payment", "paid", "refunded",
        name="order_payment_status",
        create_type=False,
    )
    order_delivery_status = postgresql.ENUM(
        "not_started", "in_progress", "delivered", "not_applicable", name="order_delivery_status",
        create_type=False,
    )

    bind = op.get_bind()
    for enum_type in (
        customer_platform, payment_method_type, order_status, order_payment_status, order_delivery_status
    ):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", customer_platform, nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=False),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("lifetime_spend", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("order_count", sa.Integer, nullable=False, server_default="0"),
        sa.Column("last_interaction_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preferred_language", sa.String(10), nullable=True),
        sa.Column("preferred_payment_method", sa.String(50), nullable=True),
        sa.Column("interests", sa.JSON, nullable=False, server_default="[]"),
        sa.UniqueConstraint("owner_id", "platform", "external_user_id", name="uq_customer_identity"),
    )
    op.create_index("ix_customers_owner_id", "customers", ["owner_id"])

    op.create_table(
        "payment_methods",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("method_type", payment_method_type, nullable=False),
        sa.Column("label", sa.String(255), nullable=False),
        sa.Column("is_enabled", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("details_encrypted", sa.Text, nullable=False, server_default=""),
    )
    op.create_index("ix_payment_methods_owner_id", "payment_methods", ["owner_id"])

    op.create_table(
        "orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("customers.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("payment_method_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("payment_methods.id", ondelete="SET NULL"), nullable=True),
        sa.Column("items", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("status", order_status, nullable=False, server_default="pending"),
        sa.Column("payment_status", order_payment_status, nullable=False, server_default="unpaid"),
        sa.Column("delivery_status", order_delivery_status, nullable=False, server_default="not_started"),
        sa.Column("notes", sa.Text, nullable=True),
        sa.Column("receipt_file_id", sa.String(500), nullable=True),
    )
    op.create_index("ix_orders_owner_id", "orders", ["owner_id"])
    op.create_index("ix_orders_customer_id", "orders", ["customer_id"])

    op.create_table(
        "order_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("note", sa.Text, nullable=True),
    )
    op.create_index("ix_order_events_order_id", "order_events", ["order_id"])

    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'new_order'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'payment_receipt_uploaded'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'order_payment_confirmed'")


def downgrade() -> None:
    op.drop_table("order_events")
    op.drop_table("orders")
    op.drop_table("payment_methods")
    op.drop_table("customers")

    bind = op.get_bind()
    for name in (
        "order_delivery_status", "order_payment_status", "order_status", "payment_method_type", "customer_platform"
    ):
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)

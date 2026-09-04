"""billing plans, subscriptions, billing events

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-30

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    billing_interval = postgresql.ENUM("monthly", "yearly", name="billing_interval", create_type=False)
    subscription_status = postgresql.ENUM("incomplete", "active", "past_due", "canceled", name="subscription_status", create_type=False)

    bind = op.get_bind()
    billing_interval.create(bind, checkfirst=True)
    subscription_status.create(bind, checkfirst=True)

    op.create_table(
        "billing_plans",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("slug", sa.String(100), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("price_amount", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="NGN"),
        sa.Column("interval", billing_interval, nullable=False, server_default="monthly"),
        sa.Column("max_agents", sa.Integer, nullable=True),
        sa.Column("max_messages_per_month", sa.Integer, nullable=True),
        sa.Column("max_knowledge_documents", sa.Integer, nullable=True),
        sa.Column("max_integrations", sa.Integer, nullable=True),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer, nullable=False, server_default="0"),
        sa.Column("paystack_plan_code", sa.String(100), nullable=True),
        sa.UniqueConstraint("slug", name="uq_billing_plans_slug"),
    )
    op.create_index("ix_billing_plans_slug", "billing_plans", ["slug"])

    op.create_table(
        "subscriptions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("billing_plans.id", ondelete="SET NULL"), nullable=True),
        sa.Column("status", subscription_status, nullable=False, server_default="incomplete"),
        sa.Column("paystack_customer_code", sa.String(100), nullable=True),
        sa.Column("paystack_subscription_code", sa.String(100), nullable=True),
        sa.Column("paystack_authorization_encrypted", sa.Text, nullable=False, server_default=""),
        sa.Column("current_period_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("owner_id", name="uq_subscriptions_owner_id"),
    )
    op.create_index("ix_subscriptions_owner_id", "subscriptions", ["owner_id"])
    op.create_index("ix_subscriptions_plan_id", "subscriptions", ["plan_id"])

    op.create_table(
        "billing_events",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("paystack_reference", sa.String(100), nullable=True),
        sa.Column("amount", sa.Numeric(12, 2), nullable=True),
        sa.Column("currency", sa.String(3), nullable=True),
        sa.Column("raw_payload", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("processed", sa.Boolean, nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_billing_events_owner_id", "billing_events", ["owner_id"])

    # Extend the notification_type enum with billing-related values added in
    # this milestone. Postgres >= 12 allows ALTER TYPE ... ADD VALUE outside
    # of being used in the same statement batch; Alembic runs each
    # migration in its own transaction, which is fine here.
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'payment_received'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'payment_failed'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'subscription_canceled'")


def downgrade() -> None:
    # Postgres has no ALTER TYPE ... DROP VALUE — downgrading the enum
    # itself isn't supported; the new notification types simply become
    # unused if you roll back the rest of this migration.
    op.drop_table("billing_events")
    op.drop_table("subscriptions")
    op.drop_table("billing_plans")

    bind = op.get_bind()
    postgresql.ENUM(name="subscription_status", create_type=False).drop(bind, checkfirst=True)
    postgresql.ENUM(name="billing_interval", create_type=False).drop(bind, checkfirst=True)

"""products, notifications, audit_logs, conversation tags/takeover, encrypted integration credentials

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBEDDING_DIM = 768


def upgrade() -> None:
    product_type = postgresql.ENUM("physical", "digital", "service", name="product_type", create_type=False)
    product_status = postgresql.ENUM("active", "draft", "archived", name="product_status", create_type=False)
    notification_type = postgresql.ENUM(
        "new_lead", "knowledge_failed", "integration_error", name="notification_type", create_type=False
    )

    bind = op.get_bind()
    product_type.create(bind, checkfirst=True)
    product_status.create(bind, checkfirst=True)
    notification_type.create(bind, checkfirst=True)

    op.create_table(
        "products",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("product_type", product_type, nullable=False),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("discount_percent", sa.Float, nullable=False, server_default="0"),
        sa.Column("inventory", sa.Integer, nullable=True),
        sa.Column("category", sa.String(255), nullable=True),
        sa.Column("variants", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("images", sa.JSON, nullable=False, server_default="[]"),
        sa.Column("status", product_status, nullable=False, server_default="draft"),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=True),
    )
    op.create_index("ix_products_owner_id", "products", ["owner_id"])

    op.create_table(
        "notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("type", notification_type, nullable=False),
        sa.Column("title", sa.String(255), nullable=False),
        sa.Column("body", sa.Text, nullable=True),
        sa.Column("is_read", sa.Boolean, nullable=False, server_default=sa.false()),
        sa.Column("context", sa.JSON, nullable=False, server_default="{}"),
    )
    op.create_index("ix_notifications_owner_id", "notifications", ["owner_id"])

    op.create_table(
        "audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("action", sa.String(100), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=True),
        sa.Column("resource_id", sa.String(100), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.Column("context", sa.JSON, nullable=False, server_default="{}"),
    )
    op.create_index("ix_audit_logs_user_id", "audit_logs", ["user_id"])

    op.add_column("conversations", sa.Column("tags", sa.JSON, nullable=False, server_default="[]"))
    op.add_column(
        "conversations", sa.Column("assigned_to_human", sa.Boolean, nullable=False, server_default=sa.false())
    )

    op.add_column(
        "platform_integrations", sa.Column("credentials_encrypted", sa.Text, nullable=False, server_default="")
    )
    op.drop_column("platform_integrations", "credentials")


def downgrade() -> None:
    op.add_column("platform_integrations", sa.Column("credentials", sa.JSON, nullable=False, server_default="{}"))
    op.drop_column("platform_integrations", "credentials_encrypted")

    op.drop_column("conversations", "assigned_to_human")
    op.drop_column("conversations", "tags")

    op.drop_table("audit_logs")
    op.drop_table("notifications")
    op.drop_table("products")

    bind = op.get_bind()
    postgresql.ENUM(name="notification_type", create_type=False).drop(bind, checkfirst=True)
    postgresql.ENUM(name="product_status", create_type=False).drop(bind, checkfirst=True)
    postgresql.ENUM(name="product_type", create_type=False).drop(bind, checkfirst=True)

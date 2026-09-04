"""whatsapp integration: business profiles, integration settings, message metadata

Revision ID: 0008
Revises: 0007
Create Date: 2026-08-02

Adds what Milestone 8 (WhatsApp Business Integration) needs on top of
the existing, already-generic Platform/Conversation/Message schema:

  - `platform_integrations.settings` (JSON) — per-integration behavior
    toggles (auto-reply, business hours, typing indicator, read
    receipts, default agent), usable by any platform.
  - `messages.platform_metadata` (JSON) — structured extras (WhatsApp
    contact cards, button/list reply ids) that don't fit the existing
    text/media columns.
  - `message_type` enum gains `video` and `contact` (WhatsApp
    distinguishes video from image/voice/document, and supports shared
    contact cards; Telegram doesn't need either yet).
  - `whatsapp_business_profiles` — a 1:1 extension of
    `platform_integrations`, matching the OrderEvent-extends-Order
    pattern rather than duplicating the integration table.

No changes to `conversations` or the core messaging tables — WhatsApp
reuses them exactly as Telegram does (Platform.WHATSAPP already existed
in the enum from Milestone 5's forward-looking design).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the transaction Alembic
    # normally wraps migrations in on Postgres — autocommit_block() steps
    # outside of it for just these two statements.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'video'")
        op.execute("ALTER TYPE message_type ADD VALUE IF NOT EXISTS 'contact'")

    op.add_column(
        "platform_integrations", sa.Column("settings", sa.JSON, nullable=False, server_default="{}")
    )
    op.add_column("messages", sa.Column("platform_metadata", sa.JSON, nullable=True))

    op.create_table(
        "whatsapp_business_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column(
            "integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("platform_integrations.id", ondelete="CASCADE"),
            nullable=False,
            unique=True,
        ),
        sa.Column("whatsapp_business_account_id", sa.String(64), nullable=False),
        sa.Column("phone_number_id", sa.String(64), nullable=False),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column("display_name", sa.String(255), nullable=True),
        sa.Column("display_phone_number", sa.String(32), nullable=True),
        sa.Column("quality_rating", sa.String(16), nullable=True),
        sa.Column("messaging_tier", sa.String(32), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("updated_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=True),
    )
    op.create_index(
        "ix_whatsapp_business_profiles_integration_id", "whatsapp_business_profiles", ["integration_id"]
    )


def downgrade() -> None:
    op.drop_table("whatsapp_business_profiles")
    op.drop_column("messages", "platform_metadata")
    op.drop_column("platform_integrations", "settings")
    # Note: Postgres doesn't support removing individual enum values —
    # downgrading message_type's added 'video'/'contact' values would
    # require recreating the type entirely. Left as-is, consistent with
    # how this codebase already treats enum-value additions as forward-only
    # (see 0005's docstring precedent for one-directional column adds).

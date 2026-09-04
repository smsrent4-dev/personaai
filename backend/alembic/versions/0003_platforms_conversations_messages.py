"""platform integrations, conversations, messages

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    platform = postgresql.ENUM(
        "telegram", "whatsapp", "discord", "instagram", "messenger", "slack", "web_widget", "voice",
        name="platform",
        create_type=False,
    )
    integration_status = postgresql.ENUM("active", "disabled", "error", name="integration_status", create_type=False)
    conversation_platform = postgresql.ENUM(
        "telegram", "whatsapp", "discord", "instagram", "messenger", "slack", "web_widget", "voice",
        name="conversation_platform",
        create_type=False,
    )
    conversation_status = postgresql.ENUM("open", "closed", name="conversation_status", create_type=False)
    message_role = postgresql.ENUM("user", "agent", "system", name="message_role", create_type=False)
    message_type = postgresql.ENUM("text", "image", "document", "voice", "location", "other", name="message_type", create_type=False)

    bind = op.get_bind()
    for enum_type in (platform, integration_status, conversation_platform, conversation_status, message_role, message_type):
        enum_type.create(bind, checkfirst=True)

    op.create_table(
        "platform_integrations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", platform, nullable=False),
        sa.Column("credentials", sa.JSON, nullable=False, server_default="{}"),
        sa.Column("webhook_secret", sa.String(64), nullable=False),
        sa.Column("external_bot_id", sa.String(128), nullable=True),
        sa.Column("external_bot_username", sa.String(255), nullable=True),
        sa.Column("status", integration_status, nullable=False, server_default="active"),
        sa.Column("error_message", sa.String(1000), nullable=True),
        sa.UniqueConstraint("owner_id", "platform", name="uq_integration_owner_platform"),
        sa.UniqueConstraint("webhook_secret", name="uq_integration_webhook_secret"),
    )
    op.create_index("ix_platform_integrations_owner_id", "platform_integrations", ["owner_id"])
    op.create_index("ix_platform_integrations_webhook_secret", "platform_integrations", ["webhook_secret"])

    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("platform", conversation_platform, nullable=False),
        sa.Column("external_conversation_id", sa.String(255), nullable=False),
        sa.Column("external_user_id", sa.String(255), nullable=True),
        sa.Column("external_user_name", sa.String(255), nullable=True),
        sa.Column("status", conversation_status, nullable=False, server_default="open"),
        sa.Column("last_message_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "owner_id", "platform", "external_conversation_id", name="uq_conversation_identity"
        ),
    )
    op.create_index("ix_conversations_owner_id", "conversations", ["owner_id"])
    op.create_index("ix_conversations_agent_id", "conversations", ["agent_id"])

    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("role", message_role, nullable=False),
        sa.Column("message_type", message_type, nullable=False, server_default="text"),
        sa.Column("content", sa.Text, nullable=True),
        sa.Column("external_message_id", sa.String(255), nullable=True),
        sa.Column("media_file_id", sa.String(500), nullable=True),
        sa.Column("latitude", sa.Float, nullable=True),
        sa.Column("longitude", sa.Float, nullable=True),
    )
    op.create_index("ix_messages_conversation_id", "messages", ["conversation_id"])
    op.create_index("ix_messages_owner_id", "messages", ["owner_id"])


def downgrade() -> None:
    op.drop_table("messages")
    op.drop_table("conversations")
    op.drop_table("platform_integrations")

    bind = op.get_bind()
    for name in ("message_type", "message_role", "conversation_status", "conversation_platform", "integration_status", "platform"):
        postgresql.ENUM(name=name, create_type=False).drop(bind, checkfirst=True)

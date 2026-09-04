"""initial schema: users, agents, refresh_tokens, verification_tokens

Revision ID: 0001
Revises:
Create Date: 2026-07-27

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    user_role = postgresql.ENUM(
        "owner",
        "admin",
        "member",
        name="user_role",
        create_type=False,
    )

    agent_type = postgresql.ENUM(
        "personal",
        "sales",
        "support",
        "opportunity",
        "custom",
        name="agent_type",
        create_type=False,
    )

    agent_status = postgresql.ENUM(
        "active",
        "paused",
        "draft",
        name="agent_status",
        create_type=False,
    )

    token_purpose = postgresql.ENUM(
        "email_verification",
        "password_reset",
        name="token_purpose",
        create_type=False,
    )

    user_role.create(bind, checkfirst=True)
    agent_type.create(bind, checkfirst=True)
    agent_status.create(bind, checkfirst=True)
    token_purpose.create(bind, checkfirst=True)

    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("hashed_password", sa.String(255), nullable=False),
        sa.Column("full_name", sa.String(255), nullable=False),
        sa.Column(
            "role",
            user_role,
            nullable=False,
            server_default="owner",
        ),
        sa.Column(
            "is_active",
            sa.Boolean,
            nullable=False,
            server_default=sa.true(),
        ),
        sa.Column(
            "is_email_verified",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("business_name", sa.String(255), nullable=True),
        sa.Column(
            "timezone",
            sa.String(64),
            nullable=False,
            server_default="UTC",
        ),
        sa.UniqueConstraint("email", name="uq_users_email"),
    )

    op.create_index("ix_users_email", "users", ["email"])
    op.create_index("ix_users_id", "users", ["id"])

    op.create_table(
        "agents",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "owner_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("avatar_url", sa.String(512), nullable=True),
        sa.Column("agent_type", agent_type, nullable=False),
        sa.Column(
            "instructions",
            sa.Text,
            nullable=False,
            server_default="",
        ),
        sa.Column(
            "model",
            sa.String(128),
            nullable=False,
            server_default="gemini-2.0-flash",
        ),
        sa.Column(
            "temperature",
            sa.Float,
            nullable=False,
            server_default="0.7",
        ),
        sa.Column(
            "permissions",
            sa.JSON,
            nullable=False,
            server_default="{}",
        ),
        sa.Column(
            "status",
            agent_status,
            nullable=False,
            server_default="draft",
        ),
    )

    op.create_index("ix_agents_owner_id", "agents", ["owner_id"])
    op.create_index("ix_agents_id", "agents", ["id"])

    op.create_table(
        "refresh_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "revoked",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("user_agent", sa.String(512), nullable=True),
        sa.Column("ip_address", sa.String(64), nullable=True),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_refresh_tokens_token_hash",
        ),
    )

    op.create_index(
        "ix_refresh_tokens_user_id",
        "refresh_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_refresh_tokens_token_hash",
        "refresh_tokens",
        ["token_hash"],
    )

    op.create_table(
        "verification_tokens",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("token_hash", sa.String(255), nullable=False),
        sa.Column("purpose", token_purpose, nullable=False),
        sa.Column(
            "expires_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "used",
            sa.Boolean,
            nullable=False,
            server_default=sa.false(),
        ),
        sa.UniqueConstraint(
            "token_hash",
            name="uq_verification_tokens_token_hash",
        ),
    )

    op.create_index(
        "ix_verification_tokens_user_id",
        "verification_tokens",
        ["user_id"],
    )
    op.create_index(
        "ix_verification_tokens_token_hash",
        "verification_tokens",
        ["token_hash"],
    )


def downgrade() -> None:
    op.drop_table("verification_tokens")
    op.drop_table("refresh_tokens")
    op.drop_table("agents")
    op.drop_table("users")

    bind = op.get_bind()

    postgresql.ENUM(
        name="token_purpose",
        create_type=False,
    ).drop(bind, checkfirst=True)

    postgresql.ENUM(
        name="agent_status",
        create_type=False,
    ).drop(bind, checkfirst=True)

    postgresql.ENUM(
        name="agent_type",
        create_type=False,
    ).drop(bind, checkfirst=True)

    postgresql.ENUM(
        name="user_role",
        create_type=False,
    ).drop(bind, checkfirst=True)

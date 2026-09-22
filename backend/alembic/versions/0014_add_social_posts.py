"""add social posts and platform publications

Revision ID: 0014
Revises: 0013
Create Date: 2026-09-19

Adds social posts and per-platform publication records for publishing
business content to connected platforms such as Telegram and WhatsApp.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0014"
down_revision: Union[str, None] = "0013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()

    social_media_type = postgresql.ENUM(
        "image",
        "video",
        name="social_media_type",
        create_type=False,
    )

    social_post_status = postgresql.ENUM(
        "draft",
        "scheduled",
        "publishing",
        "published",
        "partially_published",
        "failed",
        name="social_post_status",
        create_type=False,
    )

    social_publication_platform = postgresql.ENUM(
        "telegram",
        "whatsapp",
        name="social_publication_platform",
        create_type=False,
    )

    social_publication_status = postgresql.ENUM(
        "pending",
        "publishing",
        "published",
        "failed",
        name="social_publication_status",
        create_type=False,
    )

    social_media_type.create(bind, checkfirst=True)
    social_post_status.create(bind, checkfirst=True)
    social_publication_platform.create(bind, checkfirst=True)
    social_publication_status.create(bind, checkfirst=True)

    op.create_table(
        "social_posts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
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
        sa.Column(
            "caption",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "media_url",
            sa.String(2000),
            nullable=False,
        ),
        sa.Column(
            "media_type",
            social_media_type,
            nullable=False,
        ),
        sa.Column(
            "status",
            social_post_status,
            nullable=False,
            server_default="draft",
        ),
        sa.Column(
            "scheduled_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
    )

    op.create_index(
        "ix_social_posts_owner_id",
        "social_posts",
        ["owner_id"],
    )

    op.create_index(
        "ix_social_posts_status",
        "social_posts",
        ["status"],
    )

    op.create_index(
        "ix_social_posts_scheduled_at",
        "social_posts",
        ["scheduled_at"],
    )

    op.create_table(
        "social_post_publications",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
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
            "social_post_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "social_posts.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "integration_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "platform_integrations.id",
                ondelete="CASCADE",
            ),
            nullable=False,
        ),
        sa.Column(
            "platform",
            social_publication_platform,
            nullable=False,
        ),
        sa.Column(
            "status",
            social_publication_status,
            nullable=False,
            server_default="pending",
        ),
        sa.Column(
            "external_post_id",
            sa.String(255),
            nullable=True,
        ),
        sa.Column(
            "error_message",
            sa.Text,
            nullable=True,
        ),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            nullable=True,
        ),
        sa.UniqueConstraint(
            "social_post_id",
            "integration_id",
            name="uq_social_post_publication_integration",
        ),
    )

    op.create_index(
        "ix_social_post_publications_social_post_id",
        "social_post_publications",
        ["social_post_id"],
    )

    op.create_index(
        "ix_social_post_publications_integration_id",
        "social_post_publications",
        ["integration_id"],
    )

    op.create_index(
        "ix_social_post_publications_status",
        "social_post_publications",
        ["status"],
    )


def downgrade() -> None:
    op.drop_table("social_post_publications")
    op.drop_table("social_posts")

    bind = op.get_bind()

    postgresql.ENUM(
        name="social_publication_status",
        create_type=False,
    ).drop(bind, checkfirst=True)

    postgresql.ENUM(
        name="social_publication_platform",
        create_type=False,
    ).drop(bind, checkfirst=True)

    postgresql.ENUM(
        name="social_post_status",
        create_type=False,
    ).drop(bind, checkfirst=True)

    postgresql.ENUM(
        name="social_media_type",
        create_type=False,
    ).drop(bind, checkfirst=True)
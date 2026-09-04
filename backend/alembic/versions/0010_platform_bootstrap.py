"""platform_bootstrap lock table (fixes admin-bootstrap race condition)

Revision ID: 0010
Revises: 0009
Create Date: 2026-08-03

See app/models/platform_bootstrap.py for why this table exists: it
closes a TOCTOU race in POST /admin/bootstrap where two concurrent
callers could both read "no admin exists yet" and both get promoted —
an unauthenticated privilege-escalation path for anyone racing the
legitimate first admin.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_bootstrap",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("admin_user_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("platform_bootstrap")

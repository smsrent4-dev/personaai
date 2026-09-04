"""plan limit enforcement: plan_limit_reached notification type

Revision ID: 0009
Revises: 0008
Create Date: 2026-08-03

Companion migration to app/core/plan_limits.py's enforcement of
max_messages_per_month/max_knowledge_documents/max_integrations (only
max_agents was actually enforced before this). The message-limit path
needs a notification type to tell the owner they've hit it — the other
three limits already have a natural signal (the 402 response on the
create call itself), so this is the only schema change enforcement
required.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside the transaction Alembic
    # normally wraps migrations in on Postgres — autocommit_block() steps
    # outside of it, same as 0008's message_type additions.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'plan_limit_reached'")


def downgrade() -> None:
    # Postgres doesn't support removing individual enum values without
    # recreating the type — treated as forward-only, consistent with
    # 0008's precedent for enum-value additions.
    pass

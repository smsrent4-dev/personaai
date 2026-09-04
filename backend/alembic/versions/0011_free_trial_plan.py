"""free trial plan

Revision ID: 0011
Revises: 0010
Create Date: 2026-08-05

Adds BillingPlan.is_default_trial and seeds one "Free Trial" plan with
it set — see AuthService.register() and app/models/billing_plan.py's
docstring. Limits match what was asked for: 1 agent, 1 integration,
50 messages/month. Knowledge-document limit is left unlimited since it
wasn't part of the ask; an admin can tighten it later like any other
plan field.
"""
import uuid
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

FREE_TRIAL_PLAN_ID = uuid.uuid4()


def upgrade() -> None:
    op.add_column(
        "billing_plans",
        sa.Column("is_default_trial", sa.Boolean, nullable=False, server_default=sa.false()),
    )

    billing_plans = sa.table(
        "billing_plans",
        sa.column("id", postgresql.UUID(as_uuid=True)),
        sa.column("name", sa.String),
        sa.column("slug", sa.String),
        sa.column("description", sa.Text),
        sa.column("price_amount", sa.Numeric),
        sa.column("currency", sa.String),
        sa.column("interval", sa.String),
        sa.column("max_agents", sa.Integer),
        sa.column("max_messages_per_month", sa.Integer),
        sa.column("max_knowledge_documents", sa.Integer),
        sa.column("max_integrations", sa.Integer),
        sa.column("is_active", sa.Boolean),
        sa.column("is_default_trial", sa.Boolean),
        sa.column("sort_order", sa.Integer),
    )
    op.bulk_insert(
        billing_plans,
        [
            {
                "id": FREE_TRIAL_PLAN_ID,
                "name": "Free Trial",
                "slug": "free-trial",
                "description": "Try PersonaAI with 1 AI agent, 1 connected integration, and 50 messages/month.",
                "price_amount": 0,
                "currency": "NGN",
                "interval": "monthly",
                "max_agents": 1,
                "max_messages_per_month": 50,
                "max_knowledge_documents": None,
                "max_integrations": 1,
                "is_active": True,
                "is_default_trial": True,
                "sort_order": -1,  # sorts ahead of paid plans (BillingPlanService orders by sort_order, price_amount)
            }
        ],
    )


def downgrade() -> None:
    op.execute(f"DELETE FROM billing_plans WHERE id = '{FREE_TRIAL_PLAN_ID}'")
    op.drop_column("billing_plans", "is_default_trial")

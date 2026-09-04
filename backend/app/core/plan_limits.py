"""Plan limit enforcement.

A BillingPlan has four limit fields (max_agents, max_messages_per_month,
max_knowledge_documents, max_integrations) — all nullable = unlimited.
This module is what actually makes each one block usage rather than
just describe it; previously only max_agents was wired in, which meant
a $0 account could send unlimited messages (the expensive one — every
inbound message that reaches an agent costs a Gemini call), upload
unlimited knowledge documents, and connect unlimited integrations.
All four are enforced now:

  - enforce_agent_limit           -> AgentService.create_agent
  - enforce_knowledge_document_limit -> KnowledgeService.create_from_*
  - enforce_integration_limit     -> IntegrationService.connect_telegram /
                                      _upsert_whatsapp_integration (only
                                      when creating a *new* integration —
                                      reconnecting/rotating credentials on
                                      an existing one never counts again)
  - message limit -> see check_message_limit below; deliberately NOT an
    "enforce_*" that raises, because it's checked from inside the
    Telegram/WhatsApp webhook pipeline, not an authenticated HTTP
    request an end user is making. Raising an HTTPException there would
    just be a 500 the platform retries; instead the pipeline checks the
    result itself and degrades gracefully (see messaging_pipeline.py).

An account with no ACTIVE subscription row at all (never checked out)
is treated as unlimited here, not zero — there's no enforced "free
tier" cap in this pass; that's a product decision (what should the
actual free-tier limits be?) rather than a technical one, left for
whoever defines the real plan lineup.

"Messages this month" = all Message rows (both directions) for the
owner with created_at in the current UTC calendar month. Calendar
month rather than the subscription's billing-cycle anniversary because
`max_messages_per_month` reads as a calendar concept and Subscription
only tracks `current_period_end`, not a period start to anchor a
rolling window to.
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.billing_plan import BillingPlan
from app.models.integration import PlatformIntegration
from app.models.knowledge import KnowledgeDocument
from app.models.message import Message
from app.models.subscription import Subscription, SubscriptionStatus


async def _get_active_plan(db: AsyncSession, owner_id: uuid.UUID) -> BillingPlan | None:
    result = await db.execute(
        select(BillingPlan)
        .join(Subscription, Subscription.plan_id == BillingPlan.id)
        .where(Subscription.owner_id == owner_id, Subscription.status == SubscriptionStatus.ACTIVE)
    )
    return result.scalar_one_or_none()


def _start_of_current_month() -> datetime:
    now = datetime.now(timezone.utc)
    return now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


async def enforce_agent_limit(db: AsyncSession, owner_id: uuid.UUID) -> None:
    plan = await _get_active_plan(db, owner_id)
    if plan is None or plan.max_agents is None:
        return

    count_result = await db.execute(select(func.count()).select_from(Agent).where(Agent.owner_id == owner_id))
    current_count = count_result.scalar_one()

    if current_count >= plan.max_agents:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Your plan ({plan.name}) allows up to {plan.max_agents} agents. "
                f"Upgrade your plan to create more."
            ),
        )


async def enforce_knowledge_document_limit(db: AsyncSession, owner_id: uuid.UUID) -> None:
    plan = await _get_active_plan(db, owner_id)
    if plan is None or plan.max_knowledge_documents is None:
        return

    count_result = await db.execute(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.owner_id == owner_id)
    )
    current_count = count_result.scalar_one()

    if current_count >= plan.max_knowledge_documents:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Your plan ({plan.name}) allows up to {plan.max_knowledge_documents} knowledge "
                f"documents. Upgrade your plan, or remove an existing document, to add more."
            ),
        )


async def enforce_integration_limit(db: AsyncSession, owner_id: uuid.UUID) -> None:
    """Call this before creating a *new* PlatformIntegration row —
    never on a reconnect of an existing one (rotating a bot token or
    re-running WhatsApp's Embedded Signup shouldn't count against the
    limit a second time)."""
    plan = await _get_active_plan(db, owner_id)
    if plan is None or plan.max_integrations is None:
        return

    count_result = await db.execute(
        select(func.count()).select_from(PlatformIntegration).where(PlatformIntegration.owner_id == owner_id)
    )
    current_count = count_result.scalar_one()

    if current_count >= plan.max_integrations:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=(
                f"Your plan ({plan.name}) allows up to {plan.max_integrations} connected "
                f"integrations. Upgrade your plan, or disconnect an existing one, to add more."
            ),
        )


async def check_message_limit(db: AsyncSession, owner_id: uuid.UUID) -> tuple[bool, BillingPlan | None]:
    """Returns (limit_reached, plan). Never raises — see module
    docstring for why the message limit is checked rather than
    enforced via exception. `plan` is returned alongside the bool so
    the caller can put the plan name in the reply/notification without
    a second lookup."""
    plan = await _get_active_plan(db, owner_id)
    if plan is None or plan.max_messages_per_month is None:
        return False, plan

    count_result = await db.execute(
        select(func.count())
        .select_from(Message)
        .where(Message.owner_id == owner_id, Message.created_at >= _start_of_current_month())
    )
    current_count = count_result.scalar_one()

    return current_count >= plan.max_messages_per_month, plan

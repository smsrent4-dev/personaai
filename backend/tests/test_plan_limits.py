"""Plan limit enforcement.

Direct-DB unit tests against app/core/plan_limits.py rather than full
HTTP round trips — faster and isolates the enforcement logic itself
from the create endpoints that call it (agent/knowledge-doc creation
via HTTP is already exercised elsewhere; what wasn't tested anywhere
was whether hitting a plan's limit actually blocks anything).
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan_limits import (
    check_message_limit,
    enforce_agent_limit,
    enforce_integration_limit,
    enforce_knowledge_document_limit,
)
from app.core.security import hash_password
from app.models.agent import Agent, AgentStatus, AgentType
from app.models.billing_plan import BillingPlan
from app.models.conversation import Conversation
from app.models.integration import PlatformIntegration, generate_webhook_secret
from app.models.knowledge import KnowledgeDocument, KnowledgeSourceType, KnowledgeStatus
from app.models.message import Message, MessageRole
from app.models.platform_enums import Platform
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from fastapi import HTTPException


async def _make_user(db: AsyncSession, email: str) -> User:
    user = User(
        email=email,
        hashed_password=hash_password("StrongPass1"),
        full_name="Test Owner",
        business_name="Test Co",
        is_email_verified=True,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_active_plan(db: AsyncSession, owner: User, **limits) -> BillingPlan:
    plan = BillingPlan(
        name="Starter", slug=f"starter-{uuid.uuid4().hex[:8]}", price_amount="10.00", currency="NGN", **limits
    )
    db.add(plan)
    await db.flush()
    sub = Subscription(owner_id=owner.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE)
    db.add(sub)
    await db.flush()
    return plan


@pytest.mark.asyncio
async def test_agent_limit_still_blocks_at_cap(db_session: AsyncSession):
    owner = await _make_user(db_session, "agents@example.com")
    await _make_active_plan(db_session, owner, max_agents=1)
    db_session.add(Agent(owner_id=owner.id, name="A1", agent_type=AgentType.SUPPORT, status=AgentStatus.ACTIVE))
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await enforce_agent_limit(db_session, owner.id)
    assert exc.value.status_code == 402


@pytest.mark.asyncio
async def test_knowledge_document_limit_blocks_at_cap(db_session: AsyncSession):
    owner = await _make_user(db_session, "kb@example.com")
    await _make_active_plan(db_session, owner, max_knowledge_documents=1)
    db_session.add(
        KnowledgeDocument(
            owner_id=owner.id, title="Doc 1", source_type=KnowledgeSourceType.TEXT, status=KnowledgeStatus.READY
        )
    )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await enforce_knowledge_document_limit(db_session, owner.id)
    assert exc.value.status_code == 402
    assert "knowledge" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_knowledge_document_limit_allows_under_cap(db_session: AsyncSession):
    owner = await _make_user(db_session, "kb2@example.com")
    await _make_active_plan(db_session, owner, max_knowledge_documents=5)
    db_session.add(
        KnowledgeDocument(
            owner_id=owner.id, title="Doc 1", source_type=KnowledgeSourceType.TEXT, status=KnowledgeStatus.READY
        )
    )
    await db_session.flush()

    await enforce_knowledge_document_limit(db_session, owner.id)  # should not raise


@pytest.mark.asyncio
async def test_integration_limit_blocks_at_cap(db_session: AsyncSession):
    owner = await _make_user(db_session, "integ@example.com")
    await _make_active_plan(db_session, owner, max_integrations=1)
    db_session.add(
        PlatformIntegration(owner_id=owner.id, platform=Platform.TELEGRAM, webhook_secret=generate_webhook_secret())
    )
    await db_session.flush()

    with pytest.raises(HTTPException) as exc:
        await enforce_integration_limit(db_session, owner.id)
    assert exc.value.status_code == 402
    assert "integration" in exc.value.detail.lower()


@pytest.mark.asyncio
async def test_unlimited_plan_never_blocks(db_session: AsyncSession):
    """max_* left as None on a plan means unlimited — the whole point
    of the nullable columns; make sure enforcement respects that."""
    owner = await _make_user(db_session, "unlimited@example.com")
    await _make_active_plan(db_session, owner)  # every max_* left None
    db_session.add(Agent(owner_id=owner.id, name="A1", agent_type=AgentType.SUPPORT, status=AgentStatus.ACTIVE))
    await db_session.flush()

    await enforce_agent_limit(db_session, owner.id)  # should not raise despite having an agent already

    limit_reached, _plan = await check_message_limit(db_session, owner.id)
    assert limit_reached is False


@pytest.mark.asyncio
async def test_no_subscription_is_treated_as_unlimited(db_session: AsyncSession):
    """An account that never checked out (no Subscription row at all)
    is unlimited in this pass, not zero — see plan_limits.py's module
    docstring for why that's a deliberate placeholder, not a bug."""
    owner = await _make_user(db_session, "nosub@example.com")
    await enforce_agent_limit(db_session, owner.id)  # should not raise
    await enforce_knowledge_document_limit(db_session, owner.id)
    await enforce_integration_limit(db_session, owner.id)
    limit_reached, plan = await check_message_limit(db_session, owner.id)
    assert limit_reached is False
    assert plan is None


@pytest.mark.asyncio
async def test_message_limit_this_is_the_actual_revenue_leak_fix(db_session: AsyncSession):
    """The bug report: a free/cheap plan could send unlimited messages
    because nothing ever checked max_messages_per_month. Reproduce the
    exact scenario — a plan capped at 2 messages/month, 2 already sent
    this month — and assert the fix actually catches it."""
    owner = await _make_user(db_session, "messages@example.com")
    plan = await _make_active_plan(db_session, owner, max_messages_per_month=2)

    conversation = Conversation(owner_id=owner.id, platform=Platform.TELEGRAM, external_conversation_id="chat-1")
    db_session.add(conversation)
    await db_session.flush()

    for _ in range(2):
        db_session.add(
            Message(
                conversation_id=conversation.id, owner_id=owner.id, role=MessageRole.USER, content="hi"
            )
        )
    await db_session.flush()

    limit_reached, returned_plan = await check_message_limit(db_session, owner.id)
    assert limit_reached is True
    assert returned_plan.id == plan.id


@pytest.mark.asyncio
async def test_message_limit_not_reached_under_cap(db_session: AsyncSession):
    owner = await _make_user(db_session, "messages2@example.com")
    await _make_active_plan(db_session, owner, max_messages_per_month=10)

    conversation = Conversation(owner_id=owner.id, platform=Platform.TELEGRAM, external_conversation_id="chat-1")
    db_session.add(conversation)
    await db_session.flush()
    db_session.add(
        Message(conversation_id=conversation.id, owner_id=owner.id, role=MessageRole.USER, content="hi")
    )
    await db_session.flush()

    limit_reached, _plan = await check_message_limit(db_session, owner.id)
    assert limit_reached is False


@pytest.mark.asyncio
async def test_message_limit_only_counts_this_calendar_month(db_session: AsyncSession):
    """Messages from a previous month shouldn't count against this
    month's cap — otherwise the limit would never reset."""
    owner = await _make_user(db_session, "messages3@example.com")
    await _make_active_plan(db_session, owner, max_messages_per_month=1)

    conversation = Conversation(owner_id=owner.id, platform=Platform.TELEGRAM, external_conversation_id="chat-1")
    db_session.add(conversation)
    await db_session.flush()

    old_message = Message(conversation_id=conversation.id, owner_id=owner.id, role=MessageRole.USER, content="hi")
    db_session.add(old_message)
    await db_session.flush()
    # Backdate it to well before this month started, bypassing the
    # server_default `now()` created_at gets on insert.
    old_message.created_at = datetime.now(timezone.utc) - timedelta(days=60)
    await db_session.flush()

    limit_reached, _plan = await check_message_limit(db_session, owner.id)
    assert limit_reached is False

"""Subscription access control.

Centralized rules for deciding whether an account is allowed to use
PersonaAI's customer-facing AI/messaging features.

Billing endpoints remain accessible even when the subscription is
incomplete, past_due, canceled, or missing so the owner can choose
a plan and complete payment.

Plan quotas are handled separately by app/core/plan_limits.py.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_plan import BillingPlan
from app.models.subscription import Subscription, SubscriptionStatus


async def get_owner_subscription(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> Subscription | None:
    result = await db.execute(
        select(Subscription).where(
            Subscription.owner_id == owner_id,
        )
    )

    return result.scalar_one_or_none()


async def has_active_subscription(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> bool:
    """Return True only when the owner has a currently active subscription."""

    subscription = await get_owner_subscription(
        db,
        owner_id,
    )

    if subscription is None:
        return False

    if subscription.status != SubscriptionStatus.ACTIVE:
        return False

    # If a period end exists and has passed, access is no longer active.
    if (
        subscription.current_period_end is not None
        and subscription.current_period_end <= datetime.now(timezone.utc)
    ):
        return False

    return True


async def check_subscription_access(
    db: AsyncSession,
    owner_id: uuid.UUID,
) -> tuple[bool, Subscription | None, BillingPlan | None]:
    """Return whether the owner is allowed to use PersonaAI AI features.

    Returns:
        (allowed, subscription, plan)

    Access is allowed only when:

    1. A subscription exists.
    2. Its status is ACTIVE.
    3. Its current billing period has not expired.
    4. Its billing plan still exists and is active.

    INCOMPLETE, PAST_DUE, CANCELED, expired, or missing subscriptions
    are not allowed to use AI automation.

    Billing endpoints should NOT use this function as their access gate.
    Users need to be able to access billing and complete payment even
    when their subscription is not active.
    """

    subscription = await get_owner_subscription(
        db,
        owner_id,
    )

    if subscription is None:
        return False, None, None

    if subscription.status != SubscriptionStatus.ACTIVE:
        return False, subscription, None

    if (
        subscription.current_period_end is not None
        and subscription.current_period_end <= datetime.now(timezone.utc)
    ):
        return False, subscription, None

    if subscription.plan_id is None:
        return False, subscription, None

    result = await db.execute(
        select(BillingPlan).where(
            BillingPlan.id == subscription.plan_id,
            BillingPlan.is_active.is_(True),
        )
    )

    plan = result.scalar_one_or_none()

    if plan is None:
        return False, subscription, None

    return True, subscription, plan

"""SubscriptionService - the customer-facing half of billing: starting
a checkout, and processing the Paystack webhook events that follow it.

Every account gets a Subscription row lazily (created on first checkout
attempt, not at registration) - there's no "free plan" row for accounts
that never subscribe; get_subscription() returns None for those rather
than a synthetic free-tier row, so callers can tell "never subscribed"
apart from "subscribed to something."
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_event import BillingEvent
from app.models.billing_plan import BillingInterval, BillingPlan
from app.models.notification import NotificationType
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing.paystack_service import PaystackError, PaystackService
from app.services.billing.plan_service import BillingPlanService
from app.services.notification_service import NotificationService

logger = logging.getLogger(__name__)


class SubscriptionService:
    def __init__(self, db: AsyncSession, paystack: PaystackService | None = None):
        self.db = db
        self.paystack = paystack or PaystackService()

    async def get_subscription(self, owner_id: uuid.UUID) -> Subscription | None:
        result = await self.db.execute(select(Subscription).where(Subscription.owner_id == owner_id))
        return result.scalar_one_or_none()

    async def _get_or_create(self, owner_id: uuid.UUID) -> Subscription:
        subscription = await self.get_subscription(owner_id)
        if subscription is None:
            subscription = Subscription(owner_id=owner_id)
            self.db.add(subscription)
            await self.db.flush()
        return subscription

    async def start_checkout(self, user: User, plan_id: uuid.UUID, callback_url: str) -> dict:
        """Two very different paths depending on the plan's price:

        A free (₦0) plan needs no payment at all — there's nothing for
        Paystack to charge, so it never gets called, and the
        subscription goes straight to ACTIVE. This matters beyond just
        skipping an unnecessary API call: the old version of this method
        set status=INCOMPLETE *before* attempting anything with Paystack,
        unconditionally, for every plan including free ones — so clicking
        "Subscribe" on the free trial you were already on (which the
        frontend used to make clickable even for your current plan; also
        fixed) would immediately downgrade your working ACTIVE
        subscription to INCOMPLETE, then fail or no-op against Paystack
        for a ₦0 amount, leaving you stuck on "waiting for payment
        confirmation" for a plan that was never supposed to need any.
        See PersonaAI's changelog / alembic/versions/0012_repair_incomplete_free_subscriptions.py
        for the one-time repair of accounts this already happened to.

        A paid plan is unchanged from before: mark INCOMPLETE, then
        actually try Paystack — INCOMPLETE is the correct state to be in
        while genuinely waiting on a real payment.
        """
        plan = await BillingPlanService(self.db, self.paystack).get_plan(plan_id)
        if not plan.is_active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="This plan is no longer available")

        subscription = await self._get_or_create(user.id)

        if plan.price_amount == 0:
            subscription.plan_id = plan.id
            subscription.status = SubscriptionStatus.ACTIVE
            subscription.current_period_end = None  # free plans don't expire on a billing cycle
            await self.db.commit()
            return {"activated_directly": True}

        subscription.plan_id = plan.id
        subscription.status = SubscriptionStatus.INCOMPLETE
        await self.db.commit()

        try:
            result = await self.paystack.initialize_transaction(
                email=user.email,
                amount=plan.price_amount,
                currency=plan.currency,
                callback_url=callback_url,
                plan_code=plan.paystack_plan_code,
                metadata={"user_id": str(user.id), "plan_id": str(plan.id)},
            )
        except PaystackError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not start checkout: {exc}"
            ) from exc

        return result

    async def handle_webhook_event(self, event: dict) -> None:
        event_type = event.get("event", "unknown")
        data = event.get("data", {})

        metadata = data.get("metadata") or {}
        owner_id = None
        if metadata.get("user_id"):
            try:
                owner_id = uuid.UUID(metadata["user_id"])
            except ValueError:
                owner_id = None

        record = BillingEvent(
            owner_id=owner_id,
            event_type=event_type,
            paystack_reference=data.get("reference"),
            raw_payload=event,
        )
        self.db.add(record)

        handler = {
            "charge.success": self._handle_charge_success,
            "subscription.create": self._handle_subscription_create,
            "subscription.disable": self._handle_subscription_disable,
            "invoice.payment_failed": self._handle_invoice_failed,
        }.get(event_type)

        if handler is None:
            logger.info("Unhandled Paystack webhook event type: %s", event_type)
            await self.db.commit()
            return

        try:
            await handler(data, owner_id)
            record.processed = True
        except Exception:
            logger.error("Failed to process Paystack event %s", event_type, exc_info=True)
        await self.db.commit()

    async def _handle_charge_success(self, data: dict, owner_id: uuid.UUID | None) -> None:
        if owner_id is None:
            logger.warning("charge.success event with no resolvable user_id in metadata: %s", data.get("reference"))
            return

        subscription = await self._get_or_create(owner_id)
        subscription.status = SubscriptionStatus.ACTIVE
        subscription.paystack_customer_code = (data.get("customer") or {}).get("customer_code")

        authorization = data.get("authorization") or {}
        if authorization.get("authorization_code"):
            subscription.set_authorization(authorization)

        plan_interval = BillingInterval.MONTHLY
        if subscription.plan_id:
            plan_result = await self.db.execute(select(BillingPlan).where(BillingPlan.id == subscription.plan_id))
            plan = plan_result.scalar_one_or_none()
            if plan is not None:
                plan_interval = plan.interval

        delta = timedelta(days=365) if plan_interval == BillingInterval.YEARLY else timedelta(days=30)
        subscription.current_period_end = datetime.now(timezone.utc) + delta
        await self.db.flush()

        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.PAYMENT_RECEIVED,
            title="Payment received",
            body="Your subscription is now active.",
            context={"reference": data.get("reference")},
        )

    async def _handle_subscription_create(self, data: dict, owner_id: uuid.UUID | None) -> None:
        if owner_id is None:
            return
        subscription = await self._get_or_create(owner_id)
        subscription.paystack_subscription_code = data.get("subscription_code")
        await self.db.flush()

    async def _handle_subscription_disable(self, data: dict, owner_id: uuid.UUID | None) -> None:
        if owner_id is None:
            return
        subscription = await self.get_subscription(owner_id)
        if subscription is None:
            return
        subscription.status = SubscriptionStatus.CANCELED
        subscription.canceled_at = datetime.now(timezone.utc)
        await self.db.flush()
        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.SUBSCRIPTION_CANCELED,
            title="Subscription canceled",
            body="Your subscription has been canceled.",
        )

    async def _handle_invoice_failed(self, data: dict, owner_id: uuid.UUID | None) -> None:
        if owner_id is None:
            return
        subscription = await self.get_subscription(owner_id)
        if subscription is None:
            return
        subscription.status = SubscriptionStatus.PAST_DUE
        await self.db.flush()
        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.PAYMENT_FAILED,
            title="Payment failed",
            body="We couldn't process your latest payment. Please update your payment method.",
        )

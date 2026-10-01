"""SubscriptionService - customer-facing billing logic.
Responsibilities:
- Start free-plan activation.
- Start Paystack Card checkout with recurring subscription support.
- Start Paystack Bank Transfer checkout as a one-time payment.
- Process Paystack webhook events.
- Activate and update local subscriptions after successful payments.
Important payment-flow distinction:
CARD
-----
Paid Card checkout uses the Paystack plan_code. This allows Paystack to
create the recurring subscription after the customer completes payment.
BANK TRANSFER
-------------
Bank Transfer checkout deliberately does NOT send plan_code.
A Paystack Bank Transfer checkout is treated as a one-time payment.
When Paystack sends charge.success, the local PersonaAI subscription is
activated for the appropriate billing period.
Bank Transfer does not create the same automatic recurring Paystack
subscription that Card does. A future transfer/renewal must therefore
be handled separately.
FREE
----
Free plans never call Paystack. They are activated locally immediately.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.billing_event import BillingEvent
from app.models.billing_plan import BillingInterval, BillingPlan
from app.models.notification import NotificationType
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing.paystack_service import (
    PaystackError,
    PaystackService,
)
from app.services.billing.plan_service import BillingPlanService
from app.services.notification_service import NotificationService
logger = logging.getLogger(__name__)
PaymentMethod = Literal["card", "bank_transfer"]
class SubscriptionService:
    def __init__(
        self,
        db: AsyncSession,
        paystack: PaystackService | None = None,
    ):
        self.db = db
        self.paystack = paystack or PaystackService()
    async def get_subscription(
        self,
        owner_id: uuid.UUID,
    ) -> Subscription | None:
        """Return the user's existing subscription, if one exists."""
        result = await self.db.execute(
            select(Subscription).where(
                Subscription.owner_id == owner_id
            )
        )
        return result.scalar_one_or_none()
    async def _get_or_create(
        self,
        owner_id: uuid.UUID,
    ) -> Subscription:
        """Get the user's subscription or create it lazily."""
        subscription = await self.get_subscription(owner_id)
        if subscription is None:
            subscription = Subscription(
                owner_id=owner_id,
            )
            self.db.add(subscription)
            await self.db.flush()
        return subscription
    async def start_checkout(
        self,
        user: User,
        plan_id: uuid.UUID,
        callback_url: str,
        payment_method: PaymentMethod = "card",
    ) -> dict:
        """Start checkout for a billing plan.
        Payment methods:
        card
            Uses Paystack's recurring subscription flow.
            The Paystack plan_code is supplied.
        bank_transfer
            Uses Paystack's Bank Transfer payment channel.
            The Paystack plan_code is intentionally omitted because
            this is a one-time transfer payment.
        free plan
            Activated locally without contacting Paystack.
        """
        # ---------------------------------------------------------
        # 1. Validate payment method
        # ---------------------------------------------------------
        if payment_method not in {"card", "bank_transfer"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Unsupported payment method.",
            )
        # ---------------------------------------------------------
        # 2. Get and validate billing plan
        # ---------------------------------------------------------
        plan = await BillingPlanService(
            self.db,
            self.paystack,
        ).get_plan(plan_id)
        if not plan.is_active:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This plan is no longer available.",
            )
        # ---------------------------------------------------------
        # 3. Get/create local subscription
        # ---------------------------------------------------------
        subscription = await self._get_or_create(user.id)
        # ---------------------------------------------------------
        # 4. Free plan
        # ---------------------------------------------------------
        if plan.price_amount == 0:
            subscription.plan_id = plan.id
            subscription.status = SubscriptionStatus.ACTIVE
            # Free plans do not have a paid billing period.
            subscription.current_period_end = None
            # A free plan should not retain a previous Paystack
            # subscription from an older paid plan.
            subscription.paystack_subscription_code = None
            await self.db.commit()
            return {
                "authorization_url": None,
                "access_code": None,
                "reference": None,
                "activated_directly": True,
            }
        # ---------------------------------------------------------
        # 5. Paid plan - mark payment as pending
        # ---------------------------------------------------------
        subscription.plan_id = plan.id
        subscription.status = SubscriptionStatus.INCOMPLETE
        # Do not commit before Paystack initialization.
        #
        # If Paystack initialization fails, we roll the local
        # transaction back instead of leaving the subscription in
        # INCOMPLETE unnecessarily.
        try:
            # -----------------------------------------------------
            # CARD
            # -----------------------------------------------------
            if payment_method == "card":
                if not plan.paystack_plan_code:
                    raise PaystackError(
                        "This paid plan does not have a Paystack "
                        "plan code configured for Card payments."
                    )
                result = await self.paystack.initialize_transaction(
                    email=user.email,
                    amount=plan.price_amount,
                    currency=plan.currency,
                    callback_url=callback_url,
                    plan_code=plan.paystack_plan_code,
                    metadata={
                        "user_id": str(user.id),
                        "plan_id": str(plan.id),
                        "payment_method": "card",
                    },
                    channels=["card"],
                )
            # -----------------------------------------------------
            # BANK TRANSFER
            # -----------------------------------------------------
            else:
                result = await self.paystack.initialize_transaction(
                    email=user.email,
                    amount=plan.price_amount,
                    currency=plan.currency,
                    callback_url=callback_url,
                    # VERY IMPORTANT:
                    #
                    # Do NOT pass plan_code here.
                    #
                    # Passing plan_code turns this into Paystack's
                    # subscription transaction flow.
                    plan_code=None,
                    metadata={
                        "user_id": str(user.id),
                        "plan_id": str(plan.id),
                        "payment_method": "bank_transfer",
                    },
                    # Explicitly request Bank Transfer.
                    channels=["bank_transfer"],
                )
        except PaystackError as exc:
            await self.db.rollback()
            logger.error(
                "Failed to initialize Paystack checkout for user %s "
                "and plan %s using %s: %s",
                user.id,
                plan.id,
                payment_method,
                exc,
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Could not start checkout: {exc}",
            ) from exc
        # ---------------------------------------------------------
        # 6. Commit pending subscription
        # ---------------------------------------------------------
        await self.db.commit()
        # ---------------------------------------------------------
        # 7. Return Paystack checkout information
        # ---------------------------------------------------------
        return result
    async def handle_webhook_event(
        self,
        event: dict,
    ) -> None:
        """Process a Paystack webhook event."""
        event_type = event.get(
            "event",
            "unknown",
        )
        data = event.get(
            "data",
            {},
        )
        if not isinstance(data, dict):
            data = {}
        # ---------------------------------------------------------
        # Resolve PersonaAI user from transaction metadata
        # ---------------------------------------------------------
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        owner_id: uuid.UUID | None = None
        metadata_user_id = metadata.get("user_id")
        if metadata_user_id:
            try:
                owner_id = uuid.UUID(
                    str(metadata_user_id)
                )
            except (ValueError, TypeError):
                logger.warning(
                    "Paystack webhook contains invalid user_id "
                    "metadata: %s",
                    metadata_user_id,
                )
        # ---------------------------------------------------------
        # Store raw billing event
        # ---------------------------------------------------------
        record = BillingEvent(
            owner_id=owner_id,
            event_type=event_type,
            paystack_reference=data.get("reference"),
            raw_payload=event,
        )
        self.db.add(record)
        # ---------------------------------------------------------
        # Find event handler
        # ---------------------------------------------------------
        handler = {
            "charge.success": self._handle_charge_success,
            "subscription.create": self._handle_subscription_create,
            "subscription.disable": self._handle_subscription_disable,
            "invoice.payment_failed": self._handle_invoice_failed,
        }.get(event_type)
        if handler is None:
            logger.info(
                "Unhandled Paystack webhook event type: %s",
                event_type,
            )
            record.processed = True
            await self.db.commit()
            return
        # ---------------------------------------------------------
        # Process event
        # ---------------------------------------------------------
        try:
            await handler(
                data,
                owner_id,
            )
            record.processed = True
        except Exception:
            logger.error(
                "Failed to process Paystack event %s",
                event_type,
                exc_info=True,
            )
            # Keep the event record in the database so it can be
            # inspected/reprocessed later.
            record.processed = False
        await self.db.commit()
    async def _handle_charge_success(
        self,
        data: dict,
        owner_id: uuid.UUID | None,
    ) -> None:
        """Activate a local subscription after successful payment."""
        if owner_id is None:
            logger.warning(
                "charge.success event with no resolvable user_id "
                "in metadata. Reference: %s",
                data.get("reference"),
            )
            return
        # ---------------------------------------------------------
        # Find/create local subscription
        # ---------------------------------------------------------
        subscription = await self._get_or_create(owner_id)
        # ---------------------------------------------------------
        # Determine payment channel
        # ---------------------------------------------------------
        channel = data.get("channel")
        metadata = data.get("metadata") or {}
        if not isinstance(metadata, dict):
            metadata = {}
        payment_method = metadata.get("payment_method")
        # Paystack's transaction channel is the stronger source when
        # available.
        if channel:
            if channel == "bank_transfer":
                payment_method = "bank_transfer"
            elif channel == "card":
                payment_method = "card"
        # ---------------------------------------------------------
        # Resolve plan
        # ---------------------------------------------------------
        plan: BillingPlan | None = None
        metadata_plan_id = metadata.get("plan_id")
        if metadata_plan_id:
            try:
                plan_uuid = uuid.UUID(
                    str(metadata_plan_id)
                )
                plan_result = await self.db.execute(
                    select(BillingPlan).where(
                        BillingPlan.id == plan_uuid
                    )
                )
                plan = plan_result.scalar_one_or_none()
            except (ValueError, TypeError):
                logger.warning(
                    "charge.success event contains invalid plan_id "
                    "metadata: %s",
                    metadata_plan_id,
                )
        # Fall back to the subscription's current plan if metadata
        # doesn't contain a valid plan ID.
        if plan is None and subscription.plan_id:
            plan_result = await self.db.execute(
                select(BillingPlan).where(
                    BillingPlan.id == subscription.plan_id
                )
            )
            plan = plan_result.scalar_one_or_none()
        if plan is None:
            logger.error(
                "Cannot activate subscription for user %s: "
                "no billing plan could be resolved. Reference: %s",
                owner_id,
                data.get("reference"),
            )
            return
        # Make sure the local subscription points to the plan that
        # was actually paid for.
        subscription.plan_id = plan.id
        # ---------------------------------------------------------
        # Activate subscription
        # ---------------------------------------------------------
        subscription.status = SubscriptionStatus.ACTIVE
        # ---------------------------------------------------------
        # Store Paystack customer
        # ---------------------------------------------------------
        customer = data.get("customer") or {}
        if isinstance(customer, dict):
            customer_code = customer.get("customer_code")
            if customer_code:
                subscription.paystack_customer_code = customer_code
        # ---------------------------------------------------------
        # Store Card authorization only when appropriate
        # ---------------------------------------------------------
        #
        # Bank Transfer is a one-time payment and should not be
        # treated as a reusable recurring card authorization.
        #
        # We therefore only store the authorization when the
        # successful payment is a Card transaction.
        authorization = data.get("authorization") or {}
        is_card_payment = (
            payment_method == "card"
            or channel == "card"
        )
        if (
            is_card_payment
            and isinstance(authorization, dict)
            and authorization.get("authorization_code")
        ):
            subscription.set_authorization(
                authorization
            )
        # ---------------------------------------------------------
        # Calculate billing period
        # ---------------------------------------------------------
        if plan.interval == BillingInterval.YEARLY:
            delta = timedelta(days=365)
        else:
            delta = timedelta(days=30)
        subscription.current_period_end = (
            datetime.now(timezone.utc) + delta
        )
        await self.db.flush()
        # ---------------------------------------------------------
        # Notify user
        # ---------------------------------------------------------
        payment_label = (
            "Bank Transfer"
            if payment_method == "bank_transfer"
            else "payment"
        )
        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.PAYMENT_RECEIVED,
            title="Payment received",
            body=(
                f"Your {payment_label} payment was received "
                "and your subscription is now active."
            ),
            context={
                "reference": data.get("reference"),
                "payment_method": payment_method,
                "channel": channel,
                "plan_id": str(plan.id),
            },
        )
        logger.info(
            "Subscription activated for user %s. "
            "Plan=%s PaymentMethod=%s Channel=%s Reference=%s",
            owner_id,
            plan.id,
            payment_method,
            channel,
            data.get("reference"),
        )
    async def _handle_subscription_create(
        self,
        data: dict,
        owner_id: uuid.UUID | None,
    ) -> None:
        """Store Paystack's recurring subscription code.
        This normally applies to Card-based subscription payments.
        Bank Transfer transactions do not create a recurring
        Paystack subscription.
        """
        if owner_id is None:
            return
        subscription = await self._get_or_create(
            owner_id
        )
        subscription_code = data.get(
            "subscription_code"
        )
        if subscription_code:
            subscription.paystack_subscription_code = (
                subscription_code
            )
        await self.db.flush()
        logger.info(
            "Paystack subscription created for user %s: %s",
            owner_id,
            subscription_code,
        )
    async def _handle_subscription_disable(
        self,
        data: dict,
        owner_id: uuid.UUID | None,
    ) -> None:
        """Handle cancellation/disablement of a Paystack subscription."""
        if owner_id is None:
            return
        subscription = await self.get_subscription(
            owner_id
        )
        if subscription is None:
            return
        subscription.status = SubscriptionStatus.CANCELED
        subscription.canceled_at = datetime.now(
            timezone.utc
        )
        await self.db.flush()
        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.SUBSCRIPTION_CANCELED,
            title="Subscription canceled",
            body="Your subscription has been canceled.",
        )
        logger.info(
            "Subscription canceled for user %s",
            owner_id,
        )
    async def _handle_invoice_failed(
        self,
        data: dict,
        owner_id: uuid.UUID | None,
    ) -> None:
        """Handle a failed recurring Paystack invoice."""
        if owner_id is None:
            return
        subscription = await self.get_subscription(
            owner_id
        )
        if subscription is None:
            return
        subscription.status = SubscriptionStatus.PAST_DUE
        await self.db.flush()
        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.PAYMENT_FAILED,
            title="Payment failed",
            body=(
                "We couldn't process your latest payment. "
                "Please update your payment method."
            ),
        )
        logger.warning(
            "Subscription payment failed for user %s",
            owner_id,
        )

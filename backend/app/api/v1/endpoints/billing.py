from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession
from app.config import settings
from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.billing import (
    BillingPlanResponse,
    CheckoutRequest,
    CheckoutResponse,
    SubscriptionResponse,
)
from app.services.billing import (
    BillingPlanService,
    PaystackService,
    SubscriptionService,
)
router = APIRouter(prefix="/billing", tags=["Billing"])
@router.get("/plans", response_model=list[BillingPlanResponse])
async def list_plans(
    db: AsyncSession = Depends(get_db),
):
    return await BillingPlanService(db).list_plans(active_only=True)
@router.get(
    "/subscription",
    response_model=SubscriptionResponse | None,
)
async def get_my_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await SubscriptionService(db).get_subscription(current_user.id)
@router.post(
    "/checkout",
    response_model=CheckoutResponse,
)
async def start_checkout(
    data: CheckoutRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    callback_url = f"{settings.FRONTEND_URL}/billing/callback"
    return await SubscriptionService(db).start_checkout(
        user=current_user,
        plan_id=data.plan_id,
        callback_url=callback_url,
        payment_method=data.payment_method,
    )
@router.post(
    "/webhook/paystack",
    status_code=status.HTTP_200_OK,
)
async def paystack_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Public Paystack webhook endpoint.
    Paystack calls this endpoint directly, so there is no user
    authentication dependency. Security comes from Paystack's
    HMAC-SHA512 signature in the x-paystack-signature header.
    """
    raw_body = await request.body()
    signature = request.headers.get("x-paystack-signature")
    if not PaystackService.verify_webhook_signature(
        raw_body,
        signature,
        settings.PAYSTACK_SECRET_KEY,
    ):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid webhook signature",
        )
    event = await request.json()
    await SubscriptionService(db).handle_webhook_event(event)
    return {"status": "ok"}

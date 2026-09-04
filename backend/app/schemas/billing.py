import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.config import settings
from app.models.billing_plan import BillingInterval
from app.models.subscription import SubscriptionStatus


class BillingPlanCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=100)
    description: str | None = None
    price_amount: Decimal = Field(ge=0)
    currency: str = Field(default_factory=lambda: settings.DEFAULT_BILLING_CURRENCY, min_length=3, max_length=3)
    interval: BillingInterval = BillingInterval.MONTHLY
    max_agents: int | None = Field(default=None, ge=0)
    max_messages_per_month: int | None = Field(default=None, ge=0)
    max_knowledge_documents: int | None = Field(default=None, ge=0)
    max_integrations: int | None = Field(default=None, ge=0)
    is_default_trial: bool = False
    sort_order: int = 0


class BillingPlanUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    price_amount: Decimal | None = Field(default=None, ge=0)
    interval: BillingInterval | None = None
    max_agents: int | None = Field(default=None, ge=0)
    max_messages_per_month: int | None = Field(default=None, ge=0)
    max_knowledge_documents: int | None = Field(default=None, ge=0)
    max_integrations: int | None = Field(default=None, ge=0)
    is_default_trial: bool | None = None
    sort_order: int | None = None


class BillingPlanResponse(BaseModel):
    id: uuid.UUID
    name: str
    slug: str
    description: str | None
    price_amount: Decimal
    currency: str
    interval: BillingInterval
    max_agents: int | None
    max_messages_per_month: int | None
    max_knowledge_documents: int | None
    max_integrations: int | None
    is_active: bool
    is_default_trial: bool
    sort_order: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CheckoutRequest(BaseModel):
    plan_id: uuid.UUID


class CheckoutResponse(BaseModel):
    # None for a free (₦0) plan — see SubscriptionService.start_checkout:
    # those activate immediately without ever touching Paystack, so
    # there's no authorization URL to redirect the browser to.
    authorization_url: str | None = None
    access_code: str | None = None
    reference: str | None = None
    activated_directly: bool = False


class SubscriptionResponse(BaseModel):
    id: uuid.UUID
    plan_id: uuid.UUID | None
    status: SubscriptionStatus
    current_period_end: datetime | None
    canceled_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}

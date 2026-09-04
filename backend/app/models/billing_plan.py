"""BillingPlan - a pricing tier, editable only by a platform admin
(see app/api/v1/endpoints/admin_billing.py, gated by
require_platform_admin). Each plan mirrors a Plan on Paystack's side
(paystack_plan_code), created/updated via PaystackService whenever an
admin creates/edits a plan here - see BillingPlanService.

Limits (max_agents etc.) are nullable = unlimited. Enforcement is a
separate concern (app/core/plan_limits.py) - this model just describes
the plan, it doesn't itself block anything.

`is_default_trial`: at most one plan should have this True — it's the
plan AuthService.register() auto-subscribes every new signup to (see
its docstring). An admin can still freely edit this plan's limits (or
reassign the flag to a different plan) through the normal plan-update
endpoint; nothing about it is hardcoded outside this one flag.
"""
import enum
from decimal import Decimal

from sqlalchemy import Boolean, Enum, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.mixins import TimestampMixin, UUIDPrimaryKeyMixin


class BillingInterval(str, enum.Enum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class BillingPlan(Base, UUIDPrimaryKeyMixin, TimestampMixin):
    __tablename__ = "billing_plans"

    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    price_amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), default="NGN", nullable=False)
    interval: Mapped[BillingInterval] = mapped_column(
        Enum(BillingInterval, name="billing_interval", values_callable=lambda x: [e.value for e in x]), default=BillingInterval.MONTHLY, nullable=False
    )

    max_agents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_messages_per_month: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_knowledge_documents: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_integrations: Mapped[int | None] = mapped_column(Integer, nullable=True)

    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_default_trial: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    sort_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    paystack_plan_code: Mapped[str | None] = mapped_column(String(100), nullable=True)

    def __repr__(self) -> str:
        return f"<BillingPlan {self.slug!r} {self.price_amount} {self.currency}/{self.interval.value}>"

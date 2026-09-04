"""BillingPlanService - admin CRUD for pricing tiers, kept in sync with
a corresponding Plan on Paystack's side. Every mutation is audit-logged
since pricing changes are exactly the kind of thing an operator needs
a trail for.
"""
import re
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_plan import BillingInterval, BillingPlan
from app.models.user import User
from app.services.audit_service import AuditService
from app.services.billing.paystack_service import PaystackError, PaystackService

_PAYSTACK_INTERVAL = {BillingInterval.MONTHLY: "monthly", BillingInterval.YEARLY: "annually"}


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "plan"


class BillingPlanService:
    def __init__(self, db: AsyncSession, paystack: PaystackService | None = None):
        self.db = db
        self.paystack = paystack or PaystackService()

    async def list_plans(self, active_only: bool = False) -> list[BillingPlan]:
        stmt = select(BillingPlan).order_by(BillingPlan.sort_order, BillingPlan.price_amount)
        if active_only:
            stmt = stmt.where(BillingPlan.is_active.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_plan(self, plan_id: uuid.UUID) -> BillingPlan:
        result = await self.db.execute(select(BillingPlan).where(BillingPlan.id == plan_id))
        plan = result.scalar_one_or_none()
        if plan is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Billing plan not found")
        return plan

    async def _clear_other_default_trials(self, keep_plan_id: uuid.UUID) -> None:
        """At most one plan should be the default trial (see
        BillingPlan.is_default_trial's docstring) — setting it on one
        plan un-sets it everywhere else, rather than leaving multiple
        plans flagged and letting AuthService pick one arbitrarily."""
        await self.db.execute(
            update(BillingPlan).where(BillingPlan.id != keep_plan_id).values(is_default_trial=False)
        )

    async def create_plan(self, admin: User, data: dict) -> BillingPlan:
        slug = data.get("slug") or _slugify(data["name"])
        existing = await self.db.execute(select(BillingPlan).where(BillingPlan.slug == slug))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=f"Slug '{slug}' is already in use")

        plan = BillingPlan(**{**data, "slug": slug})
        try:
            plan.paystack_plan_code = await self.paystack.create_plan(
                name=plan.name,
                amount=plan.price_amount,
                interval=_PAYSTACK_INTERVAL[plan.interval],
                currency=plan.currency,
            )
        except PaystackError as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not create plan on Paystack: {exc}"
            ) from exc

        self.db.add(plan)
        await self.db.flush()
        if plan.is_default_trial:
            await self._clear_other_default_trials(plan.id)
        await self.db.commit()
        await self.db.refresh(plan)
        await AuditService(self.db).log(
            action="billing_plan.created", user_id=admin.id, resource_type="billing_plan", resource_id=str(plan.id),
            context={"name": plan.name, "price": str(plan.price_amount)},
        )
        return plan

    async def update_plan(self, admin: User, plan_id: uuid.UUID, updates: dict) -> BillingPlan:
        plan = await self.get_plan(plan_id)
        price_or_interval_changed = "price_amount" in updates or "interval" in updates

        for field, value in updates.items():
            setattr(plan, field, value)

        if updates.get("is_default_trial") is True:
            await self._clear_other_default_trials(plan.id)

        if price_or_interval_changed and plan.paystack_plan_code:
            try:
                await self.paystack.update_plan(
                    plan.paystack_plan_code,
                    name=plan.name,
                    amount=plan.price_amount,
                    interval=_PAYSTACK_INTERVAL[plan.interval],
                )
            except PaystackError as exc:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Could not update plan on Paystack: {exc}"
                ) from exc

        await self.db.commit()
        await self.db.refresh(plan)
        await AuditService(self.db).log(
            action="billing_plan.updated", user_id=admin.id, resource_type="billing_plan", resource_id=str(plan.id),
            context={"fields": list(updates.keys())},
        )
        return plan

    async def deactivate_plan(self, admin: User, plan_id: uuid.UUID) -> BillingPlan:
        plan = await self.get_plan(plan_id)
        plan.is_active = False
        await self.db.commit()
        await self.db.refresh(plan)
        await AuditService(self.db).log(
            action="billing_plan.deactivated", user_id=admin.id, resource_type="billing_plan",
            resource_id=str(plan.id),
        )
        return plan

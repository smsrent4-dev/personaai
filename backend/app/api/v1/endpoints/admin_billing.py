import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import require_platform_admin
from app.database import get_db
from app.models.user import User
from app.schemas.billing import BillingPlanCreate, BillingPlanResponse, BillingPlanUpdate
from app.services.billing import BillingPlanService

router = APIRouter(prefix="/admin/billing-plans", tags=["Admin: Billing Plans"])


@router.get("", response_model=list[BillingPlanResponse])
async def list_all_plans(
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await BillingPlanService(db).list_plans(active_only=False)


@router.post("", response_model=BillingPlanResponse, status_code=201)
async def create_plan(
    data: BillingPlanCreate,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await BillingPlanService(db).create_plan(admin, data.model_dump())


@router.patch("/{plan_id}", response_model=BillingPlanResponse)
async def update_plan(
    plan_id: uuid.UUID,
    data: BillingPlanUpdate,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await BillingPlanService(db).update_plan(admin, plan_id, data.model_dump(exclude_unset=True))


@router.post("/{plan_id}/deactivate", response_model=BillingPlanResponse)
async def deactivate_plan(
    plan_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await BillingPlanService(db).deactivate_plan(admin, plan_id)

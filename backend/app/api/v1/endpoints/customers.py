import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.commerce import CustomerResponse
from app.services.customer_service import CustomerService

router = APIRouter(prefix="/customers", tags=["Customers"])


@router.get("", response_model=list[CustomerResponse])
async def list_customers(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await CustomerService(db).list_customers(current_user.id)


@router.get("/{customer_id}", response_model=CustomerResponse)
async def get_customer(
    customer_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await CustomerService(db).get_customer(current_user.id, customer_id)

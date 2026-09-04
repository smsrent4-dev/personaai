import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.order import OrderStatus
from app.models.user import User
from app.schemas.commerce import OrderCreate, OrderEventResponse, OrderResponse, OrderStatusUpdate
from app.services.customer_service import CustomerService
from app.services.order_service import OrderService

router = APIRouter(prefix="/orders", tags=["Orders"])


@router.get("", response_model=list[OrderResponse])
async def list_orders(
    order_status: OrderStatus | None = None,
    customer_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await OrderService(db).list_orders(current_user.id, status_filter=order_status, customer_id=customer_id)


@router.post("", response_model=OrderResponse, status_code=201)
async def create_order(
    data: OrderCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    customer = await CustomerService(db).get_customer(current_user.id, data.customer_id)
    return await OrderService(db).create_order(
        owner_id=current_user.id,
        customer=customer,
        line_items=[item.model_dump() for item in data.items],
        payment_method_id=data.payment_method_id,
        notes=data.notes,
        recipient_name=data.recipient_name,
        recipient_phone=data.recipient_phone,
        shipping_address=data.shipping_address,
    )


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await OrderService(db).get_order(current_user.id, order_id)


@router.get("/{order_id}/timeline", response_model=list[OrderEventResponse])
async def get_order_timeline(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = OrderService(db)
    await service.get_order(current_user.id, order_id)
    return await service.get_timeline(order_id)


@router.patch("/{order_id}/status", response_model=OrderResponse)
async def update_order_status(
    order_id: uuid.UUID,
    data: OrderStatusUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await OrderService(db).update_status(current_user.id, order_id, data.status)


@router.post("/{order_id}/confirm-payment", response_model=OrderResponse)
async def confirm_payment(
    order_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await OrderService(db).confirm_payment(current_user.id, order_id)

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.commerce import PaymentMethodCreate, PaymentMethodResponse, PaymentMethodUpdate
from app.services.payment_method_service import PaymentMethodService

router = APIRouter(prefix="/payment-methods", tags=["Payment Methods"])


def _to_response(method) -> PaymentMethodResponse:
    return PaymentMethodResponse(
        id=method.id,
        method_type=method.method_type,
        label=method.label,
        is_enabled=method.is_enabled,
        details=method.get_details(),
        created_at=method.created_at,
    )


@router.get("", response_model=list[PaymentMethodResponse])
async def list_payment_methods(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    methods = await PaymentMethodService(db).list_methods(current_user.id)
    return [_to_response(m) for m in methods]


@router.post("", response_model=PaymentMethodResponse, status_code=201)
async def create_payment_method(
    data: PaymentMethodCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    details = {
        k: v
        for k, v in {
            "bank_name": data.bank_name,
            "account_name": data.account_name,
            "account_number": data.account_number,
        }.items()
        if v is not None
    }
    method = await PaymentMethodService(db).create_method(current_user.id, data.method_type, data.label, details)
    return _to_response(method)


@router.patch("/{method_id}", response_model=PaymentMethodResponse)
async def update_payment_method(
    method_id: uuid.UUID,
    data: PaymentMethodUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    details = None
    detail_fields = {
        k: v
        for k, v in {
            "bank_name": data.bank_name,
            "account_name": data.account_name,
            "account_number": data.account_number,
        }.items()
        if v is not None
    }
    if detail_fields:
        existing = await PaymentMethodService(db).get_method(current_user.id, method_id)
        details = {**existing.get_details(), **detail_fields}

    method = await PaymentMethodService(db).update_method(
        current_user.id, method_id, label=data.label, is_enabled=data.is_enabled, details=details
    )
    return _to_response(method)


@router.delete("/{method_id}", status_code=204)
async def delete_payment_method(
    method_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await PaymentMethodService(db).delete_method(current_user.id, method_id)

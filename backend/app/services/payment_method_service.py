import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.payment_method import PaymentMethod, PaymentMethodType


class PaymentMethodService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_methods(self, owner_id: uuid.UUID, enabled_only: bool = False) -> list[PaymentMethod]:
        stmt = select(PaymentMethod).where(PaymentMethod.owner_id == owner_id)
        if enabled_only:
            stmt = stmt.where(PaymentMethod.is_enabled.is_(True))
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_method(self, owner_id: uuid.UUID, method_id: uuid.UUID) -> PaymentMethod:
        result = await self.db.execute(
            select(PaymentMethod).where(PaymentMethod.id == method_id, PaymentMethod.owner_id == owner_id)
        )
        method = result.scalar_one_or_none()
        if method is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment method not found")
        return method

    async def create_method(
        self, owner_id: uuid.UUID, method_type: PaymentMethodType, label: str, details: dict
    ) -> PaymentMethod:
        method = PaymentMethod(owner_id=owner_id, method_type=method_type, label=label)
        method.set_details(details)
        self.db.add(method)
        await self.db.commit()
        await self.db.refresh(method)
        return method

    async def update_method(
        self,
        owner_id: uuid.UUID,
        method_id: uuid.UUID,
        label: str | None,
        is_enabled: bool | None,
        details: dict | None,
    ) -> PaymentMethod:
        method = await self.get_method(owner_id, method_id)
        if label is not None:
            method.label = label
        if is_enabled is not None:
            method.is_enabled = is_enabled
        if details is not None:
            method.set_details(details)
        await self.db.commit()
        await self.db.refresh(method)
        return method

    async def delete_method(self, owner_id: uuid.UUID, method_id: uuid.UUID) -> None:
        method = await self.get_method(owner_id, method_id)
        await self.db.delete(method)
        await self.db.commit()

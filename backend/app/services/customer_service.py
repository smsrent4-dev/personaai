"""CustomerService.

get_or_create_customer mirrors ConversationService's identity pattern
exactly: same (owner, platform, external_user_id) always resolves to
the same Customer row. record_purchase and update_preference are the
only two ways lifetime_spend/order_count/preferences change - both
called from OrderService/MessagingPipeline, never edited directly by
the owner (this is *observed* customer behavior, not a CRM form).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.models.platform_enums import Platform


class CustomerService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_customer(
        self,
        owner_id: uuid.UUID,
        platform: Platform,
        external_user_id: str,
        display_name: str | None = None,
    ) -> Customer:
        result = await self.db.execute(
            select(Customer).where(
                Customer.owner_id == owner_id,
                Customer.platform == platform,
                Customer.external_user_id == external_user_id,
            )
        )
        customer = result.scalar_one_or_none()

        if customer is not None:
            if display_name and customer.display_name != display_name:
                customer.display_name = display_name
            customer.last_interaction_at = datetime.now(timezone.utc)
            await self.db.flush()
            return customer

        customer = Customer(
            owner_id=owner_id,
            platform=platform,
            external_user_id=external_user_id,
            display_name=display_name,
            last_interaction_at=datetime.now(timezone.utc),
        )
        self.db.add(customer)
        await self.db.flush()
        return customer

    async def list_customers(self, owner_id: uuid.UUID) -> list[Customer]:
        result = await self.db.execute(
            select(Customer).where(Customer.owner_id == owner_id).order_by(Customer.last_interaction_at.desc())
        )
        return list(result.scalars().all())

    async def get_customer(self, owner_id: uuid.UUID, customer_id: uuid.UUID) -> Customer:
        result = await self.db.execute(
            select(Customer).where(Customer.id == customer_id, Customer.owner_id == owner_id)
        )
        customer = result.scalar_one_or_none()
        if customer is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Customer not found")
        return customer

    async def record_purchase(self, customer: Customer, amount: Decimal) -> None:
        customer.lifetime_spend = customer.lifetime_spend + amount
        customer.order_count = customer.order_count + 1
        await self.db.flush()

    async def update_preference(
        self,
        customer: Customer,
        preferred_language: str | None = None,
        preferred_payment_method: str | None = None,
        add_interest: str | None = None,
    ) -> None:
        if preferred_language:
            customer.preferred_language = preferred_language
        if preferred_payment_method:
            customer.preferred_payment_method = preferred_payment_method
        if add_interest and add_interest not in customer.interests:
            customer.interests = [*customer.interests, add_interest]
        await self.db.flush()

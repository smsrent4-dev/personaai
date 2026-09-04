import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.customer import Customer
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.customer_service import CustomerService

USER = {
    "email": "customer-owner@example.com", "password": "StrongPass1",
    "full_name": "Customer Owner", "business_name": "Cust Co",
}


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_get_or_create_customer_is_idempotent(client: AsyncClient, db_session):
    await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()

    service = CustomerService(db_session)
    first = await service.get_or_create_customer(user.id, Platform.TELEGRAM, "12345", "Jane")
    await db_session.commit()
    second = await service.get_or_create_customer(user.id, Platform.TELEGRAM, "12345", "Jane")
    await db_session.commit()

    assert first.id == second.id


@pytest.mark.asyncio
async def test_record_purchase_updates_lifetime_spend(client: AsyncClient, db_session):
    from decimal import Decimal

    await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()

    service = CustomerService(db_session)
    customer = await service.get_or_create_customer(user.id, Platform.TELEGRAM, "999")
    await db_session.commit()

    await service.record_purchase(customer, Decimal("49.99"))
    await service.record_purchase(customer, Decimal("10.01"))
    await db_session.commit()

    result = await db_session.execute(select(Customer).where(Customer.id == customer.id))
    refreshed = result.scalar_one()
    assert refreshed.lifetime_spend == Decimal("60.00")
    assert refreshed.order_count == 2


@pytest.mark.asyncio
async def test_list_customers_endpoint(client: AsyncClient, db_session):
    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()

    await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "abc", "Sam")
    await db_session.commit()

    resp = await client.get("/api/v1/customers", headers=_auth(token))
    assert resp.status_code == 200
    assert len(resp.json()) == 1
    assert resp.json()[0]["display_name"] == "Sam"


@pytest.mark.asyncio
async def test_customers_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/customers")
    assert resp.status_code == 401

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.platform_enums import Platform
from app.models.user import User
from app.services.ai.base import AIProvider
from app.services.customer_service import CustomerService

USER = {
    "email": "order-owner@example.com", "password": "StrongPass1",
    "full_name": "Order Owner", "business_name": "Order Co",
}
_KEYWORDS = ["hoodie", "cap"]


class FakeProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "reply"

    async def embed(self, texts):
        return [[1.0 if kw in t.lower() else 0.0 for kw in _KEYWORDS] for t in texts]

    async def summarize(self, text, max_words=None):
        return "summary"

    async def classify(self, text, labels):
        return labels[0]


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_product(client: AsyncClient, token: str, name: str, price: str) -> str:
    resp = await client.post(
        "/api/v1/products", json={"name": name, "product_type": "physical", "price": price}, headers=_auth(token)
    )
    product_id = resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))
    return product_id


@pytest.mark.asyncio
async def test_create_order_computes_total_from_products(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "111", "Bob")
    await db_session.commit()

    hoodie_id = await _create_product(client, token, "Hoodie", "25.00")

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": hoodie_id, "quantity": 2}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["total_amount"] == 50.0
    assert body["status"] == "pending"
    assert body["payment_status"] == "unpaid"
    assert body["items"][0]["quantity"] == 2


@pytest.mark.asyncio
async def test_order_creation_notifies_owner(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "222")
    await db_session.commit()

    product_id = await _create_product(client, token, "Cap", "10.00")
    await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )

    notif_resp = await client.get("/api/v1/notifications", headers=_auth(token))
    assert any(n["type"] == "new_order" for n in notif_resp.json())


@pytest.mark.asyncio
async def test_confirm_payment_marks_paid_and_updates_customer_spend(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "333")
    await db_session.commit()

    product_id = await _create_product(client, token, "Hoodie", "30.00")
    order_resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    order_id = order_resp.json()["id"]

    confirm_resp = await client.post(f"/api/v1/orders/{order_id}/confirm-payment", headers=_auth(token))
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["payment_status"] == "paid"
    assert confirm_resp.json()["status"] == "confirmed"

    customer_resp = await client.get(f"/api/v1/customers/{customer.id}", headers=_auth(token))
    assert customer_resp.json()["lifetime_spend"] == 30.0
    assert customer_resp.json()["order_count"] == 1


@pytest.mark.asyncio
async def test_order_timeline_records_events(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "444")
    await db_session.commit()

    product_id = await _create_product(client, token, "Hoodie", "20.00")
    order_resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    order_id = order_resp.json()["id"]

    await client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "preparing"}, headers=_auth(token))
    await client.post(f"/api/v1/orders/{order_id}/confirm-payment", headers=_auth(token))

    timeline_resp = await client.get(f"/api/v1/orders/{order_id}/timeline", headers=_auth(token))
    event_types = [e["event_type"] for e in timeline_resp.json()]
    assert "order_created" in event_types
    assert "status_changed" in event_types
    assert "payment_confirmed" in event_types


@pytest.mark.asyncio
async def test_order_with_unknown_product_returns_404(client: AsyncClient, db_session):
    import uuid

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "555")
    await db_session.commit()

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": str(uuid.uuid4()), "quantity": 1}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_order_decrements_product_inventory(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "666")
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Hoodie", "product_type": "physical", "price": "25.00", "inventory": 5},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 3}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )

    product_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert product_resp.json()["inventory"] == 2


@pytest.mark.asyncio
async def test_order_rejects_when_insufficient_stock(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "777")
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Limited Cap", "product_type": "physical", "price": "15.00", "inventory": 1},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 2}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    assert resp.status_code == 409

    # Stock must be unchanged — the rejected order shouldn't have partially decremented it.
    product_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert product_resp.json()["inventory"] == 1


@pytest.mark.asyncio
async def test_unlimited_stock_product_has_no_inventory_check(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "888")
    await db_session.commit()

    # inventory omitted -> None -> unlimited
    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Digital Guide", "product_type": "digital", "price": "5.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1000}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    assert resp.status_code == 201

    product_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert product_resp.json()["inventory"] is None


@pytest.mark.asyncio
async def test_cancelling_order_restocks_inventory(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "999")
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Hoodie", "product_type": "physical", "price": "25.00", "inventory": 5},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    order_resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 2}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    order_id = order_resp.json()["id"]

    mid_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert mid_resp.json()["inventory"] == 3

    await client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "cancelled"}, headers=_auth(token))

    after_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert after_resp.json()["inventory"] == 5

    timeline_resp = await client.get(f"/api/v1/orders/{order_id}/timeline", headers=_auth(token))
    assert any(e["event_type"] == "stock_restocked" for e in timeline_resp.json())


@pytest.mark.asyncio
async def test_cancelling_twice_does_not_double_restock(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "1010")
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Hoodie", "product_type": "physical", "price": "25.00", "inventory": 5},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    order_resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1}], "recipient_name": "Test Recipient", "shipping_address": "123 Test St, Lagos"},
        headers=_auth(token),
    )
    order_id = order_resp.json()["id"]

    await client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "cancelled"}, headers=_auth(token))
    # Cancelling an already-cancelled order should not restock a second time.
    await client.patch(f"/api/v1/orders/{order_id}/status", json={"status": "cancelled"}, headers=_auth(token))

    product_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert product_resp.json()["inventory"] == 5


@pytest.mark.asyncio
async def test_multi_item_order_failure_does_not_partially_decrement_stock(
    client: AsyncClient, db_session, monkeypatch
):
    """If item 2 of a multi-item order fails (insufficient stock), item 1's
    already-executed decrement must roll back too — get_db() rolls back
    the whole session on any exception, so this is really a regression
    guard on that behavior specifically for multi-item orders."""
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "1111")
    await db_session.commit()

    plentiful_id = await _create_product(client, token, "Hoodie", "25.00")
    await client.patch(f"/api/v1/products/{plentiful_id}", json={"inventory": 10}, headers=_auth(token))
    scarce_id = await _create_product(client, token, "Cap", "10.00")
    await client.patch(f"/api/v1/products/{scarce_id}", json={"inventory": 1}, headers=_auth(token))

    resp = await client.post(
        "/api/v1/orders",
        json={
            "customer_id": str(customer.id),
            "items": [
                {"product_id": plentiful_id, "quantity": 3},
                {"product_id": scarce_id, "quantity": 5},  # only 1 in stock
            ],
            "recipient_name": "Test Recipient",
            "shipping_address": "123 Test St, Lagos",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 409

    plentiful_resp = await client.get(f"/api/v1/products/{plentiful_id}", headers=_auth(token))
    assert plentiful_resp.json()["inventory"] == 10  # unchanged, not partially decremented


@pytest.mark.asyncio
async def test_orders_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/orders")
    assert resp.status_code == 401


# ---------- delivery details (recipient name / phone / shipping address) ----------


@pytest.mark.asyncio
async def test_physical_order_without_shipping_address_is_rejected(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "2001")
    await db_session.commit()

    product_id = await _create_product(client, token, "Hoodie", "25.00")

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1}]},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert "shipping address" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_physical_order_without_shipping_address_does_not_decrement_stock(
    client: AsyncClient, db_session, monkeypatch
):
    """The bug caught while building this: validating AFTER decrementing
    stock would mean a rejected order (missing address) could still
    silently take units out of inventory. Confirms it doesn't."""
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "2002")
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Hoodie", "product_type": "physical", "price": "25.00", "inventory": 5},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 2}]},
        headers=_auth(token),
    )
    assert resp.status_code == 400

    product_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert product_resp.json()["inventory"] == 5  # unchanged


@pytest.mark.asyncio
async def test_physical_order_with_delivery_details_succeeds_and_stores_them(
    client: AsyncClient, db_session, monkeypatch
):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "2003")
    await db_session.commit()

    product_id = await _create_product(client, token, "Hoodie", "25.00")

    resp = await client.post(
        "/api/v1/orders",
        json={
            "customer_id": str(customer.id),
            "items": [{"product_id": product_id, "quantity": 1}],
            "recipient_name": "Chidinma Okafor",
            "recipient_phone": "+2348012345678",
            "shipping_address": "14 Admiralty Way, Lekki Phase 1, Lagos",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["recipient_name"] == "Chidinma Okafor"
    assert body["recipient_phone"] == "+2348012345678"
    assert body["shipping_address"] == "14 Admiralty Way, Lekki Phase 1, Lagos"


@pytest.mark.asyncio
async def test_digital_product_order_does_not_require_delivery_details(client: AsyncClient, db_session, monkeypatch):
    fake = FakeProvider()
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)

    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    customer = await CustomerService(db_session).get_or_create_customer(user.id, Platform.TELEGRAM, "2004")
    await db_session.commit()

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Digital Guide", "product_type": "digital", "price": "5.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        "/api/v1/orders",
        json={"customer_id": str(customer.id), "items": [{"product_id": product_id, "quantity": 1}]},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["shipping_address"] is None

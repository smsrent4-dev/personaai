import hashlib
import hmac
import json
import uuid

import httpx
import pytest
import respx
from httpx import AsyncClient
from sqlalchemy import select

from app.config import settings
from app.models.billing_plan import BillingPlan
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.services.billing.paystack_service import PAYSTACK_API_BASE

ADMIN = {
    "email": "billing-admin@example.com", "password": "StrongPass1",
    "full_name": "Billing Admin", "business_name": "Admin Co",
}
CUSTOMER = {
    "email": "billing-customer@example.com", "password": "StrongPass1",
    "full_name": "Billing Customer", "business_name": "Cust Co",
}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _mock_paystack_plan_endpoints():
    respx.post(f"{PAYSTACK_API_BASE}/plan").mock(
        return_value=httpx.Response(200, json={"status": True, "message": "ok", "data": {"plan_code": "PLN_test1"}})
    )
    respx.put(f"{PAYSTACK_API_BASE}/plan/PLN_test1").mock(
        return_value=httpx.Response(200, json={"status": True, "message": "ok", "data": {}})
    )


@pytest.mark.asyncio
@respx.mock
async def test_admin_creates_plan_and_it_syncs_to_paystack(client: AsyncClient):
    _mock_paystack_plan_endpoints()
    admin_token = await _register_and_login(client, ADMIN)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(admin_token))

    resp = await client.post(
        "/api/v1/admin/billing-plans",
        json={"name": "Growth", "price_amount": "99.00", "currency": "NGN", "max_agents": 5},
        headers=_auth(admin_token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["slug"] == "growth"
    assert body["price_amount"] == 99.0


@pytest.mark.asyncio
async def test_regular_user_cannot_create_plan(client: AsyncClient):
    token = await _register_and_login(client, CUSTOMER)
    resp = await client.post(
        "/api/v1/admin/billing-plans",
        json={"name": "Growth", "price_amount": "99.00"},
        headers=_auth(token),
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
@respx.mock
async def test_deactivated_plan_hidden_from_customer_listing(client: AsyncClient):
    _mock_paystack_plan_endpoints()
    admin_token = await _register_and_login(client, ADMIN)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(admin_token))

    create_resp = await client.post(
        "/api/v1/admin/billing-plans", json={"name": "Growth", "price_amount": "99.00"}, headers=_auth(admin_token)
    )
    plan_id = create_resp.json()["id"]

    customer_token = await _register_and_login(client, CUSTOMER)
    visible = await client.get("/api/v1/billing/plans", headers=_auth(customer_token))
    assert any(p["id"] == plan_id for p in visible.json())

    await client.post(f"/api/v1/admin/billing-plans/{plan_id}/deactivate", headers=_auth(admin_token))

    visible_after = await client.get("/api/v1/billing/plans", headers=_auth(customer_token))
    assert not any(p["id"] == plan_id for p in visible_after.json())

    admin_listing = await client.get("/api/v1/admin/billing-plans", headers=_auth(admin_token))
    assert any(p["id"] == plan_id for p in admin_listing.json())


@pytest.mark.asyncio
@respx.mock
async def test_updating_price_resyncs_paystack_plan(client: AsyncClient):
    _mock_paystack_plan_endpoints()
    admin_token = await _register_and_login(client, ADMIN)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(admin_token))

    create_resp = await client.post(
        "/api/v1/admin/billing-plans", json={"name": "Growth", "price_amount": "99.00"}, headers=_auth(admin_token)
    )
    plan_id = create_resp.json()["id"]

    update_route = respx.put(f"{PAYSTACK_API_BASE}/plan/PLN_test1").mock(
        return_value=httpx.Response(200, json={"status": True, "message": "ok", "data": {}})
    )
    update_resp = await client.patch(
        f"/api/v1/admin/billing-plans/{plan_id}", json={"price_amount": "149.00"}, headers=_auth(admin_token)
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["price_amount"] == 149.0
    assert update_route.called


@pytest.mark.asyncio
@respx.mock
async def test_checkout_creates_incomplete_subscription(client: AsyncClient, db_session):
    _mock_paystack_plan_endpoints()
    admin_token = await _register_and_login(client, ADMIN)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(admin_token))
    create_resp = await client.post(
        "/api/v1/admin/billing-plans", json={"name": "Growth", "price_amount": "99.00"}, headers=_auth(admin_token)
    )
    plan_id = create_resp.json()["id"]

    respx.post(f"{PAYSTACK_API_BASE}/transaction/initialize").mock(
        return_value=httpx.Response(
            200,
            json={
                "status": True,
                "message": "ok",
                "data": {
                    "authorization_url": "https://checkout.paystack.com/xyz",
                    "access_code": "xyz",
                    "reference": "ref_abc",
                },
            },
        )
    )

    customer_token = await _register_and_login(client, CUSTOMER)
    checkout_resp = await client.post(
        "/api/v1/billing/checkout", json={"plan_id": plan_id}, headers=_auth(customer_token)
    )
    assert checkout_resp.status_code == 200
    assert checkout_resp.json()["reference"] == "ref_abc"

    sub_resp = await client.get("/api/v1/billing/subscription", headers=_auth(customer_token))
    assert sub_resp.json()["status"] == "incomplete"
    assert sub_resp.json()["plan_id"] == plan_id


@pytest.mark.asyncio
@respx.mock
async def test_checkout_on_a_free_plan_activates_immediately_without_paystack(client: AsyncClient, db_session):
    """Regression test for the actual reported bug: clicking "Subscribe"
    on a ₦0 plan — including your own current free plan, which the
    frontend used to make clickable — must never leave you on
    "incomplete"/"waiting for payment confirmation".

    Plan *creation* still syncs to Paystack regardless of price (that's
    BillingPlanService.create_plan, unchanged and out of scope here —
    the real Free Trial plan is seeded directly via migration, bypassing
    this service entirely), so that part is mocked below. What's NOT
    mocked is /transaction/initialize — if the checkout fix regressed
    and tried to call Paystack for a ₦0 charge, respx would have nothing
    registered for that endpoint and the request would error, which is
    itself part of what this test proves.
    """
    _mock_paystack_plan_endpoints()
    admin_token = await _register_and_login(client, ADMIN)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(admin_token))
    create_resp = await client.post(
        "/api/v1/admin/billing-plans",
        json={"name": "Free Trial", "price_amount": "0.00", "max_agents": 1},
        headers=_auth(admin_token),
    )
    plan_id = create_resp.json()["id"]

    customer_token = await _register_and_login(client, CUSTOMER)
    checkout_resp = await client.post(
        "/api/v1/billing/checkout", json={"plan_id": plan_id}, headers=_auth(customer_token)
    )
    assert checkout_resp.status_code == 200
    body = checkout_resp.json()
    assert body["activated_directly"] is True
    assert body["authorization_url"] is None

    sub_resp = await client.get("/api/v1/billing/subscription", headers=_auth(customer_token))
    assert sub_resp.json()["status"] == "active"
    assert sub_resp.json()["plan_id"] == plan_id

    # Clicking "Subscribe" again on the plan you're already on (exactly
    # what triggered the original bug) must be a harmless no-op, not a
    # second downgrade-then-fail.
    second_resp = await client.post(
        "/api/v1/billing/checkout", json={"plan_id": plan_id}, headers=_auth(customer_token)
    )
    assert second_resp.status_code == 200
    assert second_resp.json()["activated_directly"] is True
    sub_resp_2 = await client.get("/api/v1/billing/subscription", headers=_auth(customer_token))
    assert sub_resp_2.json()["status"] == "active"


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(client: AsyncClient):
    resp = await client.post(
        "/api/v1/billing/webhook/paystack",
        content=b'{"event":"charge.success","data":{}}',
        headers={"x-paystack-signature": "not-a-real-signature", "Content-Type": "application/json"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_webhook_charge_success_activates_subscription(client: AsyncClient, db_session):
    token = await _register_and_login(client, CUSTOMER)
    result = await db_session.execute(select(User).where(User.email == CUSTOMER["email"]))
    user = result.scalar_one()

    body_dict = {
        "event": "charge.success",
        "data": {
            "reference": "ref_xyz",
            "metadata": {"user_id": str(user.id)},
            "customer": {"customer_code": "CUS_123"},
            "authorization": {"authorization_code": "AUTH_abc"},
        },
    }
    raw_body = json.dumps(body_dict).encode()
    signature = hmac.new(settings.PAYSTACK_SECRET_KEY.encode("utf-8"), raw_body, hashlib.sha512).hexdigest()

    resp = await client.post(
        "/api/v1/billing/webhook/paystack",
        content=raw_body,
        headers={"x-paystack-signature": signature, "Content-Type": "application/json"},
    )
    assert resp.status_code == 200

    sub_resp = await client.get("/api/v1/billing/subscription", headers=_auth(token))
    assert sub_resp.json()["status"] == "active"

    notif_resp = await client.get("/api/v1/notifications", headers=_auth(token))
    assert any(n["type"] == "payment_received" for n in notif_resp.json())


@pytest.mark.asyncio
@respx.mock
async def test_plan_limit_enforcement_on_agent_creation(client: AsyncClient, db_session):
    _mock_paystack_plan_endpoints()
    admin_token = await _register_and_login(client, ADMIN)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(admin_token))
    plan_resp = await client.post(
        "/api/v1/admin/billing-plans",
        json={"name": "Tiny", "price_amount": "10.00", "max_agents": 5},
        headers=_auth(admin_token),
    )
    plan_id = plan_resp.json()["id"]

    customer_token = await _register_and_login(client, CUSTOMER)
    result = await db_session.execute(select(User).where(User.email == CUSTOMER["email"]))
    user = result.scalar_one()

    plan_result = await db_session.execute(select(BillingPlan).where(BillingPlan.id == uuid.UUID(plan_id)))
    plan = plan_result.scalar_one()

    subscription = Subscription(owner_id=user.id, plan_id=plan.id, status=SubscriptionStatus.ACTIVE)
    db_session.add(subscription)
    await db_session.commit()

    fifth = await client.post(
        "/api/v1/agents",
        json={"name": "Fifth Agent", "agent_type": "custom", "instructions": "x"},
        headers=_auth(customer_token),
    )
    assert fifth.status_code == 201

    sixth = await client.post(
        "/api/v1/agents",
        json={"name": "Sixth Agent", "agent_type": "custom", "instructions": "x"},
        headers=_auth(customer_token),
    )
    assert sixth.status_code == 402

"""Free trial plan: auto-assignment at registration, agent-seeding
respecting the plan's cap, and admin editability.

Note: the actual "Free Trial" plan row is seeded by a data migration
(alembic/versions/0011_free_trial_plan.py) — migrations don't run in
this test suite (tests build the schema via Base.metadata.create_all,
see conftest.py), so every test here creates its own BillingPlan with
is_default_trial=True directly. This also means every OTHER existing
test in the suite (which doesn't create such a plan) is unaffected:
AuthService._get_default_trial_plan() finds nothing, registration
proceeds unsubscribed exactly as before this feature existed, and all
4 default agents get seeded as before — see test_agents.py /
test_router.py, unchanged by this feature.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.billing_plan import BillingPlan
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User

REGISTER_PAYLOAD = {
    "email": "trial-user@example.com",
    "password": "StrongPass1",
    "full_name": "Trial User",
    "business_name": "Trial Co",
}

ADMIN_PAYLOAD = {
    "email": "trial-admin@example.com",
    "password": "StrongPass1",
    "full_name": "Trial Admin",
    "business_name": "Admin Co",
}


async def _seed_free_trial_plan(db_session: AsyncSession) -> BillingPlan:
    plan = BillingPlan(
        name="Free Trial",
        slug="free-trial",
        price_amount=0,
        max_agents=1,
        max_messages_per_month=50,
        max_integrations=1,
        is_active=True,
        is_default_trial=True,
    )
    db_session.add(plan)
    await db_session.commit()
    await db_session.refresh(plan)
    return plan


@pytest.mark.asyncio
async def test_new_signup_auto_subscribed_to_free_trial(client: AsyncClient, db_session: AsyncSession):
    plan = await _seed_free_trial_plan(db_session)

    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    user_id = resp.json()["id"]

    sub_result = await db_session.execute(select(Subscription).where(Subscription.owner_id == user_id))
    subscription = sub_result.scalar_one()
    assert subscription.plan_id == plan.id
    assert subscription.status == SubscriptionStatus.ACTIVE


@pytest.mark.asyncio
async def test_free_trial_signup_gets_exactly_one_agent(client: AsyncClient, db_session: AsyncSession):
    """The actual bug this would otherwise cause: seeding all 4 default
    agents (the pre-existing behavior) onto a 1-agent-max plan would put
    a brand-new account over its own limit before it ever does anything —
    enforce_agent_limit would then block them from ever creating another
    agent, and there's no UI path to delete 3 of the 4 to get compliant
    again. Seeding must respect the cap from the start."""
    await _seed_free_trial_plan(db_session)

    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    user_id = resp.json()["id"]

    login = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]}
    )
    token = login.json()["access_token"]

    agents_resp = await client.get("/api/v1/agents", headers={"Authorization": f"Bearer {token}"})
    agents = agents_resp.json()
    assert len(agents) == 1
    assert agents[0]["name"] == "Sales Agent"  # the single most useful default for a commerce platform


@pytest.mark.asyncio
async def test_signup_without_a_seeded_trial_plan_is_unaffected(client: AsyncClient):
    """No BillingPlan.is_default_trial=True row exists in this test —
    registration should proceed exactly as it did before this feature:
    unsubscribed, all 4 default agents seeded."""
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    user_id = resp.json()["id"]

    login = await client.post(
        "/api/v1/auth/login", json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]}
    )
    token = login.json()["access_token"]

    agents_resp = await client.get("/api/v1/agents", headers={"Authorization": f"Bearer {token}"})
    assert len(agents_resp.json()) == 4


@pytest.mark.asyncio
async def test_admin_can_edit_free_trial_limits(client: AsyncClient, db_session: AsyncSession):
    plan = await _seed_free_trial_plan(db_session)

    await client.post("/api/v1/auth/register", json=ADMIN_PAYLOAD)
    login = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_PAYLOAD["email"], "password": ADMIN_PAYLOAD["password"]}
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}

    admin_result = await db_session.execute(select(User).where(User.email == ADMIN_PAYLOAD["email"]))
    admin_user = admin_result.scalar_one()
    admin_user.is_platform_admin = True
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/admin/billing-plans/{plan.id}",
        json={"max_messages_per_month": 100, "max_agents": 2},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["max_messages_per_month"] == 100
    assert body["max_agents"] == 2
    assert body["is_default_trial"] is True  # unrelated fields untouched by a partial update


@pytest.mark.asyncio
async def test_only_one_plan_can_be_the_default_trial(client: AsyncClient, db_session: AsyncSession):
    plan_a = await _seed_free_trial_plan(db_session)
    plan_b = BillingPlan(name="Starter", slug="starter", price_amount=1000, is_default_trial=False)
    db_session.add(plan_b)
    await db_session.commit()
    await db_session.refresh(plan_b)

    await client.post("/api/v1/auth/register", json=ADMIN_PAYLOAD)
    login = await client.post(
        "/api/v1/auth/login", json={"email": ADMIN_PAYLOAD["email"], "password": ADMIN_PAYLOAD["password"]}
    )
    token = login.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    admin_result = await db_session.execute(select(User).where(User.email == ADMIN_PAYLOAD["email"]))
    admin_user = admin_result.scalar_one()
    admin_user.is_platform_admin = True
    await db_session.commit()

    resp = await client.patch(
        f"/api/v1/admin/billing-plans/{plan_b.id}", json={"is_default_trial": True}, headers=headers
    )
    assert resp.status_code == 200

    await db_session.refresh(plan_a)
    assert plan_a.is_default_trial is False  # flipped off when plan_b was flipped on

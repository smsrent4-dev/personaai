import pytest
from httpx import AsyncClient

USER_A = {"email": "admin-a@example.com", "password": "StrongPass1", "full_name": "Admin A", "business_name": "A Co"}
USER_B = {"email": "admin-b@example.com", "password": "StrongPass1", "full_name": "Regular B", "business_name": "B Co"}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_bootstrap_race_is_closed_at_the_database_level(client: AsyncClient, db_session):
    """Regression test for the TOCTOU privilege-escalation fix: two
    concurrent bootstrap attempts must not both be able to claim admin.
    The old implementation checked `count(is_platform_admin) == 0` then
    separately set the flag — two requests could both pass the check
    before either committed. The fix claims a single fixed-PK row
    first; PK uniqueness is enforced by the database itself, so this
    proves the second claim is rejected at the storage layer, not just
    "usually" rejected by request ordering."""
    from sqlalchemy.exc import IntegrityError

    from app.models.platform_bootstrap import PlatformBootstrap

    token_a = await _register_and_login(client, USER_A)
    resp_a = await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    assert resp_a.status_code == 200

    token_b = await _register_and_login(client, USER_B)
    me_b = (await client.get("/api/v1/auth/me", headers=_auth(token_b))).json()

    with pytest.raises(IntegrityError):
        db_session.add(PlatformBootstrap(id=1, admin_user_id=me_b["id"]))
        await db_session.flush()
    await db_session.rollback()


@pytest.mark.asyncio
async def test_bootstrap_promotes_first_caller(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    resp = await client.post("/api/v1/admin/bootstrap", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["is_platform_admin"] is True

    me = await client.get("/api/v1/auth/me", headers=_auth(token))
    assert me.json()["is_platform_admin"] is True


@pytest.mark.asyncio
async def test_bootstrap_fails_once_an_admin_exists(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))

    token_b = await _register_and_login(client, USER_B)
    resp = await client.post("/api/v1/admin/bootstrap", headers=_auth(token_b))
    assert resp.status_code == 409

    me_b = await client.get("/api/v1/auth/me", headers=_auth(token_b))
    assert me_b.json()["is_platform_admin"] is False


@pytest.mark.asyncio
async def test_regular_user_cannot_access_admin_endpoints(client: AsyncClient):
    token = await _register_and_login(client, USER_B)
    resp = await client.get("/api/v1/admin/stats", headers=_auth(token))
    assert resp.status_code == 403

    resp = await client.get("/api/v1/admin/users", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_can_list_all_users_across_accounts(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    await _register_and_login(client, USER_B)

    resp = await client.get("/api/v1/admin/users", headers=_auth(token_a))
    assert resp.status_code == 200
    emails = {row["email"] for row in resp.json()}
    assert emails == {USER_A["email"], USER_B["email"]}

    row_a = next(r for r in resp.json() if r["email"] == USER_A["email"])
    assert row_a["agent_count"] == 4


@pytest.mark.asyncio
async def test_admin_can_suspend_and_reactivate_another_user(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    token_b = await _register_and_login(client, USER_B)

    users = (await client.get("/api/v1/admin/users", headers=_auth(token_a))).json()
    user_b_id = next(r["id"] for r in users if r["email"] == USER_B["email"])

    suspend_resp = await client.post(f"/api/v1/admin/users/{user_b_id}/suspend", headers=_auth(token_a))
    assert suspend_resp.status_code == 200
    assert suspend_resp.json()["is_active"] is False

    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": USER_B["email"], "password": USER_B["password"]}
    )
    assert login_resp.status_code == 403

    reactivate_resp = await client.post(f"/api/v1/admin/users/{user_b_id}/reactivate", headers=_auth(token_a))
    assert reactivate_resp.json()["is_active"] is True

    login_resp = await client.post(
        "/api/v1/auth/login", json={"email": USER_B["email"], "password": USER_B["password"]}
    )
    assert login_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_cannot_suspend_own_account(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    admin = await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    admin_id = admin.json()["id"]

    resp = await client.post(f"/api/v1/admin/users/{admin_id}/suspend", headers=_auth(token_a))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_admin_can_promote_another_user(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    token_b = await _register_and_login(client, USER_B)

    users = (await client.get("/api/v1/admin/users", headers=_auth(token_a))).json()
    user_b_id = next(r["id"] for r in users if r["email"] == USER_B["email"])

    promote_resp = await client.post(f"/api/v1/admin/users/{user_b_id}/promote", headers=_auth(token_a))
    assert promote_resp.json()["is_platform_admin"] is True

    stats_resp = await client.get("/api/v1/admin/stats", headers=_auth(token_b))
    assert stats_resp.status_code == 200


@pytest.mark.asyncio
async def test_admin_dashboard_requires_platform_admin(client: AsyncClient):
    token = await _register_and_login(client, USER_B)
    resp = await client.get("/api/v1/admin/dashboard", headers=_auth(token))
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_dashboard_reflects_real_data(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    await _register_and_login(client, USER_B)

    resp = await client.get("/api/v1/admin/dashboard", headers=_auth(token_a))
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_users"] == 2
    assert data["active_agents"] >= 0
    assert len(data["revenue_last_7_days"]) == 7
    assert data["monthly_revenue"] == 0  # no BillingEvents in this test
    assert isinstance(data["subscription_distribution"], list)
    assert len(data["recent_users"]) <= 5
    assert data["system_health"]["database_ok"] is True


@pytest.mark.asyncio
async def test_platform_stats_reflect_real_data(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    await _register_and_login(client, USER_B)

    resp = await client.get("/api/v1/admin/stats", headers=_auth(token_a))
    stats = resp.json()
    assert stats["total_users"] == 2
    assert stats["total_agents"] == 8
    assert len(stats["signups_last_7_days"]) == 7


@pytest.mark.asyncio
async def test_admin_actions_are_audited(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    await client.post("/api/v1/admin/bootstrap", headers=_auth(token_a))
    await _register_and_login(client, USER_B)

    users = (await client.get("/api/v1/admin/users", headers=_auth(token_a))).json()
    user_b_id = next(r["id"] for r in users if r["email"] == USER_B["email"])
    await client.post(f"/api/v1/admin/users/{user_b_id}/suspend", headers=_auth(token_a))

    logs = (await client.get("/api/v1/audit-logs", headers=_auth(token_a))).json()
    assert any(log["action"] == "user.suspended" for log in logs)
    assert any(log["action"] == "platform_admin.bootstrapped" for log in logs)

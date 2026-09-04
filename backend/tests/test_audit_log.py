import pytest
from httpx import AsyncClient

USER = {
    "email": "audit-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Audit Owner",
    "business_name": "Audit Co",
}


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_successful_login_is_audited(client: AsyncClient):
    token = await _register_and_login(client)
    logs = (await client.get("/api/v1/audit-logs", headers=_auth(token))).json()
    assert any(log["action"] == "login.success" for log in logs)


@pytest.mark.asyncio
async def test_failed_login_is_audited(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=USER)
    await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": "WrongPassword1"})

    token = (
        await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    ).json()["access_token"]

    logs = (await client.get("/api/v1/audit-logs", headers=_auth(token))).json()
    assert any(log["action"] == "login.failed" for log in logs)


@pytest.mark.asyncio
async def test_agent_deletion_is_audited(client: AsyncClient):
    token = await _register_and_login(client)
    agents = (await client.get("/api/v1/agents", headers=_auth(token))).json()
    agent_id = agents[0]["id"]

    await client.delete(f"/api/v1/agents/{agent_id}", headers=_auth(token))

    logs = (await client.get("/api/v1/audit-logs", headers=_auth(token))).json()
    matching = [log for log in logs if log["action"] == "agent.deleted"]
    assert len(matching) == 1
    assert matching[0]["resource_id"] == agent_id


@pytest.mark.asyncio
async def test_audit_logs_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/audit-logs")
    assert resp.status_code == 401

import pytest
from httpx import AsyncClient

USER_A = {"email": "owner-a@example.com", "password": "StrongPass1", "full_name": "Owner A", "business_name": "A Co"}
USER_B = {"email": "owner-b@example.com", "password": "StrongPass1", "full_name": "Owner B", "business_name": "B Co"}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post(
        "/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]}
    )
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_registration_seeds_four_default_agents(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    resp = await client.get("/api/v1/agents", headers=_auth(token))
    assert resp.status_code == 200
    agents = resp.json()
    assert len(agents) == 4
    names = {a["name"] for a in agents}
    assert names == {"Personal Agent", "Sales Agent", "Customer Support Agent", "Opportunity Agent"}
    assert all(a["status"] == "active" for a in agents)
    # Default agents' instructions should be real content, not empty stubs.
    assert all(len(a["instructions"]) > 50 for a in agents)


@pytest.mark.asyncio
async def test_create_custom_agent(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    payload = {
        "name": "Warranty Agent",
        "description": "Handles warranty claims",
        "agent_type": "custom",
        "instructions": "You handle warranty claims for the business.",
        "temperature": 0.5,
    }
    resp = await client.post("/api/v1/agents", json=payload, headers=_auth(token))
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Warranty Agent"
    assert body["status"] == "draft"  # custom agents default to draft, not auto-active

    list_resp = await client.get("/api/v1/agents", headers=_auth(token))
    assert len(list_resp.json()) == 5


@pytest.mark.asyncio
async def test_update_agent(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    agents = (await client.get("/api/v1/agents", headers=_auth(token))).json()
    agent_id = agents[0]["id"]

    resp = await client.patch(
        f"/api/v1/agents/{agent_id}",
        json={"temperature": 1.2, "status": "paused"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["temperature"] == 1.2
    assert body["status"] == "paused"


@pytest.mark.asyncio
async def test_delete_agent(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    agents = (await client.get("/api/v1/agents", headers=_auth(token))).json()
    agent_id = agents[0]["id"]

    resp = await client.delete(f"/api/v1/agents/{agent_id}", headers=_auth(token))
    assert resp.status_code == 204

    get_resp = await client.get(f"/api/v1/agents/{agent_id}", headers=_auth(token))
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_cannot_access_another_users_agent(client: AsyncClient):
    token_a = await _register_and_login(client, USER_A)
    token_b = await _register_and_login(client, USER_B)

    a_agents = (await client.get("/api/v1/agents", headers=_auth(token_a))).json()
    a_agent_id = a_agents[0]["id"]

    resp = await client.get(f"/api/v1/agents/{a_agent_id}", headers=_auth(token_b))
    assert resp.status_code == 404

    resp = await client.patch(
        f"/api/v1/agents/{a_agent_id}", json={"temperature": 1.9}, headers=_auth(token_b)
    )
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/agents/{a_agent_id}", headers=_auth(token_b))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_agents_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/agents")
    assert resp.status_code == 401

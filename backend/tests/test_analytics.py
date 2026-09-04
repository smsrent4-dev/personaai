import pytest
from httpx import AsyncClient

USER = {
    "email": "analytics-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Analytics Owner",
    "business_name": "Analytics Co",
}


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_analytics_summary_on_fresh_account(client: AsyncClient):
    token = await _register_and_login(client)
    resp = await client.get("/api/v1/analytics/summary", headers=_auth(token))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total_conversations"] == 0
    assert body["total_messages"] == 0
    assert body["active_agents"] == 4
    assert body["knowledge_documents_ready"] == 0
    assert body["active_products"] == 0
    assert body["messages_by_agent"] == []


@pytest.mark.asyncio
async def test_messages_per_day_covers_requested_range_with_real_zeros(client: AsyncClient):
    token = await _register_and_login(client)
    resp = await client.get("/api/v1/analytics/summary?days=7", headers=_auth(token))
    series = resp.json()["messages_per_day"]
    assert len(series) == 7
    assert all(point["count"] == 0 for point in series)
    dates = [point["date"] for point in series]
    assert dates == sorted(dates)


@pytest.mark.asyncio
async def test_analytics_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/analytics/summary")
    assert resp.status_code == 401

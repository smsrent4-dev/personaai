import pytest
from httpx import AsyncClient

from app.services.ai.base import AIProvider

USER = {"email": "router-owner@example.com", "password": "StrongPass1", "full_name": "Router Owner", "business_name": "Router Co"}


class FakeProvider(AIProvider):
    name = "fake"

    def __init__(self, forced_label: str | None = None):
        self.forced_label = forced_label
        self.last_labels: list[str] | None = None

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "fake response"

    async def embed(self, texts):
        return [[0.0] for _ in texts]

    async def summarize(self, text, max_words=None):
        return "fake summary"

    async def classify(self, text, labels):
        self.last_labels = labels
        return self.forced_label or labels[0]


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_router_picks_agent_matching_classify_result(client: AsyncClient, monkeypatch):
    token = await _register_and_login(client)

    fake = FakeProvider(forced_label="Sales Agent")
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: fake)

    resp = await client.post(
        "/api/v1/router/route", json={"message": "How much for the website package?"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Sales Agent"
    # All 4 default agent names should have been offered as classification labels.
    assert set(fake.last_labels) == {"Personal Agent", "Sales Agent", "Customer Support Agent", "Opportunity Agent"}


@pytest.mark.asyncio
async def test_router_requires_at_least_one_active_agent(client: AsyncClient, monkeypatch):
    token = await _register_and_login(client)

    # Pause every default agent.
    agents = (await client.get("/api/v1/agents", headers=_auth(token))).json()
    for agent in agents:
        await client.patch(f"/api/v1/agents/{agent['id']}", json={"status": "paused"}, headers=_auth(token))

    fake = FakeProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: fake)

    resp = await client.post("/api/v1/router/route", json={"message": "hello"}, headers=_auth(token))
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_router_skips_classification_with_single_active_agent(client: AsyncClient, monkeypatch):
    token = await _register_and_login(client)

    agents = (await client.get("/api/v1/agents", headers=_auth(token))).json()
    for agent in agents:
        if agent["name"] != "Personal Agent":
            await client.patch(f"/api/v1/agents/{agent['id']}", json={"status": "paused"}, headers=_auth(token))

    fake = FakeProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: fake)

    resp = await client.post("/api/v1/router/route", json={"message": "hi"}, headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json()["name"] == "Personal Agent"
    # classify() should never have been called — only one active agent.
    assert fake.last_labels is None


@pytest.mark.asyncio
async def test_router_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/router/route", json={"message": "hi"})
    assert resp.status_code == 401

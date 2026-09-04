import pytest
from httpx import AsyncClient

from app.services.ai.base import AIProvider

USER = {
    "email": "memory-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Memory Owner",
    "business_name": "Memory Co",
}

_KEYWORDS = ["lagos", "flutter", "friday", "email"]


class FakeEmbeddingProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "fake"

    async def embed(self, texts):
        return [[1.0 if kw in t.lower() else 0.1 for kw in _KEYWORDS] for t in texts]

    async def summarize(self, text, max_words=None):
        return "fake summary"

    async def classify(self, text, labels):
        return labels[0]


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_provider(monkeypatch):
    provider = FakeEmbeddingProvider()
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: provider)
    return provider


@pytest.mark.asyncio
async def test_create_and_list_memory(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/memory",
        json={"memory_type": "fact", "content": "The office is in Lagos."},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["memory_type"] == "fact"
    assert resp.json()["source"] == "manual"

    list_resp = await client.get("/api/v1/memory", headers=_auth(token))
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_memory_search_ranks_relevant_entry_first(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    await client.post(
        "/api/v1/memory",
        json={"memory_type": "fact", "content": "Our office is now in Lagos."},
        headers=_auth(token),
    )
    await client.post(
        "/api/v1/memory",
        json={"memory_type": "preference", "content": "Never mention Flutter in replies."},
        headers=_auth(token),
    )

    resp = await client.post(
        "/api/v1/memory/search", json={"query": "Where is the Lagos office?"}, headers=_auth(token)
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert results[0]["memory"]["content"] == "Our office is now in Lagos."


@pytest.mark.asyncio
async def test_delete_memory(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/memory", json={"memory_type": "event", "content": "Launch event on Friday."}, headers=_auth(token)
    )
    memory_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/memory/{memory_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    list_resp = await client.get("/api/v1/memory", headers=_auth(token))
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_memory_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/memory")
    assert resp.status_code == 401

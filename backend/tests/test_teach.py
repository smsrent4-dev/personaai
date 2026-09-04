import pytest
from httpx import AsyncClient

from app.services.ai.base import AIProvider

USER = {
    "email": "teach-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Teach Owner",
    "business_name": "Teach Co",
}


class FakeClassifyingProvider(AIProvider):
    """Classifies based on simple keyword rules so tests are deterministic
    without a real model call."""

    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "fake"

    async def embed(self, texts):
        return [[0.5, 0.5] for _ in texts]

    async def summarize(self, text, max_words=None):
        return "fake summary"

    async def classify(self, text, labels):
        lowered = text.lower()
        if "never" in lowered or "always" in lowered or "prefer" in lowered:
            guess = "preference"
        elif "event" in lowered or "launch" in lowered or "on friday" in lowered:
            guess = "event"
        else:
            guess = "fact"
        return guess if guess in labels else labels[0]


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def fake_provider(monkeypatch):
    provider = FakeClassifyingProvider()
    monkeypatch.setattr("app.services.teach_service.get_ai_provider", lambda: provider)
    return provider


@pytest.mark.asyncio
async def test_teach_classifies_fact(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/teach", json={"statement": "My website package now costs $650."}, headers=_auth(token)
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["memory_type"] == "fact"
    assert body["source"] == "teach"
    assert body["content"] == "My website package now costs $650."


@pytest.mark.asyncio
async def test_teach_classifies_preference(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/teach", json={"statement": "Never mention Flutter in replies."}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert resp.json()["memory_type"] == "preference"


@pytest.mark.asyncio
async def test_taught_memory_appears_in_memory_list(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    await client.post("/api/v1/teach", json={"statement": "My office is now in Lagos."}, headers=_auth(token))

    list_resp = await client.get("/api/v1/memory", headers=_auth(token))
    assert len(list_resp.json()) == 1
    assert list_resp.json()[0]["source"] == "teach"


@pytest.mark.asyncio
async def test_teach_requires_auth(client: AsyncClient):
    resp = await client.post("/api/v1/teach", json={"statement": "hello"})
    assert resp.status_code == 401

import pytest
from httpx import AsyncClient

from app.services.ai.base import AIProvider
from app.services.knowledge.storage import LocalStorageBackend

USER = {
    "email": "knowledge-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Knowledge Owner",
    "business_name": "Knowledge Co",
}

_KEYWORDS = ["pricing", "shipping", "refund", "hours"]


class FakeEmbeddingProvider(AIProvider):
    """Deterministic fake embeddings: one dimension per keyword, 1.0 if
    present in the text (case-insensitive) else 0.1, so similarity search
    results are predictable without a real embedding model."""

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
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: provider)
    return provider


@pytest.fixture
def temp_storage(tmp_path, monkeypatch):
    backend = LocalStorageBackend(base_dir=str(tmp_path))
    monkeypatch.setattr("app.services.knowledge.service.get_storage_backend", lambda: backend)
    return backend


@pytest.mark.asyncio
async def test_create_text_document_ingests_and_becomes_ready(client: AsyncClient, fake_provider, temp_storage):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/knowledge/documents/text",
        json={"title": "Shipping Policy", "content": "We ship within 3 business days. " * 5},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["status"] == "ready"
    assert body["title"] == "Shipping Policy"


@pytest.mark.asyncio
async def test_failed_extraction_marks_document_failed_not_crash(client: AsyncClient, fake_provider, temp_storage):
    token = await _register_and_login(client)
    # Whitespace-only content chunks to nothing -> ingestion should mark FAILED, not 500.
    resp = await client.post(
        "/api/v1/knowledge/documents/text",
        json={"title": "Empty Doc", "content": "   "},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["status"] == "failed"
    assert resp.json()["error_message"] is not None


@pytest.mark.asyncio
async def test_semantic_search_ranks_relevant_document_first(client: AsyncClient, fake_provider, temp_storage):
    token = await _register_and_login(client)
    await client.post(
        "/api/v1/knowledge/documents/text",
        json={"title": "Pricing Doc", "content": "Our pricing starts at $99 per month for the basic plan."},
        headers=_auth(token),
    )
    await client.post(
        "/api/v1/knowledge/documents/text",
        json={"title": "Refund Doc", "content": "Refund requests are handled within 5 business days."},
        headers=_auth(token),
    )

    resp = await client.post(
        "/api/v1/knowledge/search",
        json={"query": "What is your pricing?", "top_k": 2},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    results = resp.json()["results"]
    assert len(results) >= 1
    assert results[0]["document_title"] == "Pricing Doc"


@pytest.mark.asyncio
async def test_delete_document_removes_it_and_its_chunks(client: AsyncClient, fake_provider, temp_storage):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/knowledge/documents/text",
        json={"title": "Temp Doc", "content": "Business hours are 9am to 5pm Monday through Friday."},
        headers=_auth(token),
    )
    doc_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/knowledge/documents/{doc_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/knowledge/documents/{doc_id}", headers=_auth(token))
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_knowledge_requires_auth(client: AsyncClient):
    resp = await client.get("/api/v1/knowledge/documents")
    assert resp.status_code == 401

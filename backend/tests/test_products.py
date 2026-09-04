import pytest
from httpx import AsyncClient

from app.services.ai.base import AIProvider

USER = {
    "email": "product-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Product Owner",
    "business_name": "Product Co",
}

_KEYWORDS = ["website", "logo", "hosting"]


class FakeEmbeddingProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "fake reply mentioning the product"

    async def embed(self, texts):
        return [[1.0 if kw in t.lower() else 0.1 for kw in _KEYWORDS] for t in texts]

    async def summarize(self, text, max_words=None):
        return "summary"

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
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: provider)
    return provider


@pytest.mark.asyncio
async def test_create_and_list_product(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/products",
        json={
            "name": "Website Package",
            "description": "A full business website build",
            "product_type": "service",
            "price": "500.00",
            "category": "web",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "Website Package"
    assert body["price"] == 500.0
    assert body["status"] == "draft"

    list_resp = await client.get("/api/v1/products", headers=_auth(token))
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
async def test_update_product_reembeds_on_text_change(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Logo Design", "product_type": "digital", "price": "150.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/products/{product_id}",
        json={"status": "active", "price": "175.00"},
        headers=_auth(token),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["status"] == "active"
    assert update_resp.json()["price"] == 175.0


@pytest.mark.asyncio
async def test_product_search_ranks_relevant_product_first(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    website = await client.post(
        "/api/v1/products",
        json={"name": "Website Package", "product_type": "service", "price": "500.00"},
        headers=_auth(token),
    )
    hosting = await client.post(
        "/api/v1/products",
        json={"name": "Hosting Plan", "product_type": "service", "price": "10.00"},
        headers=_auth(token),
    )
    # Only active products are searchable.
    for resp in (website, hosting):
        await client.patch(f"/api/v1/products/{resp.json()['id']}", json={"status": "active"}, headers=_auth(token))

    search_resp = await client.post(
        "/api/v1/products/search", json={"query": "How much is the website?"}, headers=_auth(token)
    )
    assert search_resp.status_code == 200
    results = search_resp.json()["results"]
    assert results[0]["product"]["name"] == "Website Package"


@pytest.mark.asyncio
async def test_draft_products_excluded_from_search(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    await client.post(
        "/api/v1/products",
        json={"name": "Website Package", "product_type": "service", "price": "500.00"},
        headers=_auth(token),
    )  # left in draft status

    search_resp = await client.post(
        "/api/v1/products/search", json={"query": "website"}, headers=_auth(token)
    )
    assert search_resp.json()["results"] == []


@pytest.mark.asyncio
async def test_delete_product(client: AsyncClient, fake_provider):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Temp Product", "product_type": "physical", "price": "20.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    get_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert get_resp.status_code == 404


@pytest.mark.asyncio
async def test_create_product_with_variants(client: AsyncClient, fake_provider):
    """Regression test: variants used to be built with Decimal price_delta,
    which SQLAlchemy's JSON column can't serialize. price_delta is a float now."""
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/products",
        json={
            "name": "T-Shirt",
            "product_type": "physical",
            "price": "25.00",
            "variants": [
                {"name": "Small", "price_delta": 0, "sku": "TS-S"},
                {"name": "Large", "price_delta": 5.0, "sku": "TS-L"},
            ],
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    variants = resp.json()["variants"]
    assert len(variants) == 2
    assert variants[1]["price_delta"] == 5.0


@pytest.mark.asyncio
async def test_products_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/products")
    assert resp.status_code == 401

"""Product image upload/serve/remove — the "user can add a business
product image" half of the feature (the other half, sending it back
to a matching customer message, is covered by test_product_photos.py).
"""
import pytest
from httpx import AsyncClient

from app.services.knowledge.storage import LocalStorageBackend

USER = {
    "email": "image-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Image Owner",
    "business_name": "Image Co",
}

TINY_PNG = bytes.fromhex(
    "89504e470d0a1a0a0000000d4948445200000001000000010802000000907753"
    "de0000000c4944415478da6360000002000155bfeb1b0000000049454e44ae426082"
)


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def wire_storage(monkeypatch, tmp_path):
    backend = LocalStorageBackend(base_dir=str(tmp_path))
    # Both the service (upload) and the endpoint module (public serving)
    # import get_storage_backend by name into their own module namespace —
    # patching one doesn't affect the other, so both need pointing at the
    # exact same backend instance for an uploaded file to be readable
    # back out again in the same test.
    monkeypatch.setattr("app.services.product_service.get_storage_backend", lambda: backend)
    monkeypatch.setattr("app.api.v1.endpoints.products.get_storage_backend", lambda: backend)
    return backend


@pytest.mark.asyncio
async def test_upload_image_appends_a_fetchable_url(client: AsyncClient, wire_storage):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Crocs Shoes", "product_type": "physical", "price": "20.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    assert create_resp.json()["images"] == []

    upload_resp = await client.post(
        f"/api/v1/products/{product_id}/images",
        files={"file": ("crocs.png", TINY_PNG, "image/png")},
        headers=_auth(token),
    )
    assert upload_resp.status_code == 201
    images = upload_resp.json()["images"]
    assert len(images) == 1
    image_url = images[0]
    assert "/api/v1/products/images/" in image_url

    # The URL is meant to be publicly fetchable (Telegram/WhatsApp's own
    # servers hit it, not ours with a JWT) — confirm it works with NO
    # auth header at all.
    path = image_url.split("/api/v1", 1)[1]
    serve_resp = await client.get(f"/api/v1{path}")
    assert serve_resp.status_code == 200
    assert serve_resp.headers["content-type"] == "image/png"
    assert serve_resp.content == TINY_PNG


@pytest.mark.asyncio
async def test_upload_rejects_non_image_content_type(client: AsyncClient, wire_storage):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Crocs Shoes", "product_type": "physical", "price": "20.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]

    resp = await client.post(
        f"/api/v1/products/{product_id}/images",
        files={"file": ("notes.txt", b"hello", "text/plain")},
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_remove_image(client: AsyncClient, wire_storage):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Crocs Shoes", "product_type": "physical", "price": "20.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]

    upload_resp = await client.post(
        f"/api/v1/products/{product_id}/images",
        files={"file": ("crocs.png", TINY_PNG, "image/png")},
        headers=_auth(token),
    )
    image_url = upload_resp.json()["images"][0]

    remove_resp = await client.delete(
        f"/api/v1/products/{product_id}/images", params={"image_url": image_url}, headers=_auth(token)
    )
    assert remove_resp.status_code == 200
    assert remove_resp.json()["images"] == []


@pytest.mark.asyncio
async def test_serving_unknown_image_returns_404(client: AsyncClient, wire_storage):
    resp = await client.get("/api/v1/products/images/nobody/does-not-exist.png")
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_serving_rejects_path_traversal(client: AsyncClient, wire_storage):
    resp = await client.get("/api/v1/products/images/../../etc/passwd")
    assert resp.status_code in (404, 400)

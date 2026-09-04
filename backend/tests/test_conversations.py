import pytest
from httpx import AsyncClient

USER_A = {"email": "conv-a@example.com", "password": "StrongPass1", "full_name": "Conv A", "business_name": "A Co"}
USER_B = {"email": "conv-b@example.com", "password": "StrongPass1", "full_name": "Conv B", "business_name": "B Co"}


async def _register_and_login(client: AsyncClient, payload: dict) -> str:
    await client.post("/api/v1/auth/register", json=payload)
    resp = await client.post("/api/v1/auth/login", json={"email": payload["email"], "password": payload["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_empty_conversation_list_for_new_user(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    resp = await client.get("/api/v1/conversations", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_nonexistent_conversation_returns_404(client: AsyncClient):
    token = await _register_and_login(client, USER_A)
    import uuid

    resp = await client.get(f"/api/v1/conversations/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_conversations_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/conversations")
    assert resp.status_code == 401

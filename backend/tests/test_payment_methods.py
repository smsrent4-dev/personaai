import pytest
from httpx import AsyncClient

USER = {
    "email": "payment-owner@example.com", "password": "StrongPass1",
    "full_name": "Payment Owner", "business_name": "Payment Co",
}


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_create_bank_transfer_method(client: AsyncClient):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/payment-methods",
        json={
            "method_type": "bank_transfer",
            "label": "Main account",
            "bank_name": "GTBank",
            "account_name": "Ada's Studio",
            "account_number": "0123456789",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["details"]["bank_name"] == "GTBank"
    assert body["details"]["account_number"] == "0123456789"


@pytest.mark.asyncio
async def test_bank_details_stored_encrypted_not_plaintext(client: AsyncClient, db_session):
    from sqlalchemy import select
    from app.models.payment_method import PaymentMethod

    token = await _register_and_login(client)
    await client.post(
        "/api/v1/payment-methods",
        json={
            "method_type": "bank_transfer",
            "label": "Main account",
            "bank_name": "GTBank",
            "account_name": "Ada's Studio",
            "account_number": "0123456789",
        },
        headers=_auth(token),
    )

    result = await db_session.execute(select(PaymentMethod))
    method = result.scalar_one()
    assert "0123456789" not in method.details_encrypted
    assert method.get_details()["account_number"] == "0123456789"


@pytest.mark.asyncio
async def test_create_cash_method_with_no_sensitive_details(client: AsyncClient):
    token = await _register_and_login(client)
    resp = await client.post(
        "/api/v1/payment-methods",
        json={"method_type": "cash", "label": "In-store cash"},
        headers=_auth(token),
    )
    assert resp.status_code == 201
    assert resp.json()["details"] == {}


@pytest.mark.asyncio
async def test_update_payment_method_label_and_disable(client: AsyncClient):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/payment-methods", json={"method_type": "cash", "label": "Cash"}, headers=_auth(token)
    )
    method_id = create_resp.json()["id"]

    update_resp = await client.patch(
        f"/api/v1/payment-methods/{method_id}",
        json={"label": "Cash on pickup", "is_enabled": False},
        headers=_auth(token),
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["label"] == "Cash on pickup"
    assert update_resp.json()["is_enabled"] is False


@pytest.mark.asyncio
async def test_delete_payment_method(client: AsyncClient):
    token = await _register_and_login(client)
    create_resp = await client.post(
        "/api/v1/payment-methods", json={"method_type": "cash", "label": "Cash"}, headers=_auth(token)
    )
    method_id = create_resp.json()["id"]

    delete_resp = await client.delete(f"/api/v1/payment-methods/{method_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    list_resp = await client.get("/api/v1/payment-methods", headers=_auth(token))
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_payment_methods_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/payment-methods")
    assert resp.status_code == 401

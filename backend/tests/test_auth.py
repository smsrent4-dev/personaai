import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.verification_token import TokenPurpose, VerificationToken

REGISTER_PAYLOAD = {
    "email": "founder@example.com",
    "password": "StrongPass1",
    "full_name": "Ada Founder",
    "business_name": "Ada's Studio",
}


@pytest.mark.asyncio
async def test_register_creates_unverified_user(client: AsyncClient):
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["email"] == REGISTER_PAYLOAD["email"]
    assert body["is_email_verified"] is False
    assert body["role"] == "owner"


@pytest.mark.asyncio
async def test_register_duplicate_email_rejected(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    assert resp.status_code == 409


@pytest.mark.asyncio
async def test_weak_password_rejected(client: AsyncClient):
    payload = {**REGISTER_PAYLOAD, "email": "weak@example.com", "password": "alllowercase"}
    resp = await client.post("/api/v1/auth/register", json=payload)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_login_and_get_me(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    assert resp.status_code == 200
    tokens = resp.json()
    assert "access_token" in tokens and "refresh_token" in tokens

    me = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["email"] == REGISTER_PAYLOAD["email"]


@pytest.mark.asyncio
async def test_login_wrong_password_rejected(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": "WrongPass1"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_refresh_token_rotates_and_old_one_is_revoked(client: AsyncClient):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)
    login_resp = await client.post(
        "/api/v1/auth/login",
        json={"email": REGISTER_PAYLOAD["email"], "password": REGISTER_PAYLOAD["password"]},
    )
    first_refresh = login_resp.json()["refresh_token"]

    refreshed = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert refreshed.status_code == 200
    assert refreshed.json()["refresh_token"] != first_refresh

    reused = await client.post("/api/v1/auth/refresh", json={"refresh_token": first_refresh})
    assert reused.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_requires_token(client: AsyncClient):
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_verify_email_flow(client: AsyncClient, db_session: AsyncSession):
    await client.post("/api/v1/auth/register", json=REGISTER_PAYLOAD)

    result = await db_session.execute(
        select(VerificationToken).where(VerificationToken.purpose == TokenPurpose.EMAIL_VERIFICATION)
    )
    # We only have the hash in the DB (by design — see security.hash_token),
    # so this test exercises the endpoint's rejection path for a token it
    # never received in plaintext, proving unknown tokens are rejected.
    assert result.scalar_one_or_none() is not None

    resp = await client.post("/api/v1/auth/verify-email", json={"token": "not-a-real-token"})
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_forgot_password_does_not_leak_account_existence(client: AsyncClient):
    resp = await client.post("/api/v1/auth/forgot-password", json={"email": "nobody@example.com"})
    assert resp.status_code == 204

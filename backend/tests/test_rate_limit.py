import pytest
from httpx import AsyncClient

from app.core.rate_limit import MAX_REQUESTS_PER_WINDOW


@pytest.mark.asyncio
async def test_rate_limit_kicks_in_after_threshold(client: AsyncClient):
    responses = []
    for i in range(MAX_REQUESTS_PER_WINDOW + 3):
        resp = await client.post(
            "/api/v1/auth/login", json={"email": f"nobody{i}@example.com", "password": "wrong"}
        )
        responses.append(resp.status_code)

    assert 429 in responses
    first_429_index = responses.index(429)
    assert first_429_index == MAX_REQUESTS_PER_WINDOW
    assert all(code == 401 for code in responses[:first_429_index])


@pytest.mark.asyncio
async def test_rate_limit_does_not_affect_unrelated_endpoints(client: AsyncClient):
    for _ in range(MAX_REQUESTS_PER_WINDOW + 5):
        resp = await client.get("/api/health")
        assert resp.status_code == 200

import httpx
import pytest
import respx
from httpx import AsyncClient

from app.services.platforms.telegram_adapter import TELEGRAM_API_BASE

USER = {
    "email": "integration-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Integration Owner",
    "business_name": "Integration Co",
}


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
@respx.mock
async def test_connect_telegram_success(client: AsyncClient):
    token = await _register_and_login(client)

    respx.get(f"{TELEGRAM_API_BASE}/bot111:validtoken/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"id": 111, "username": "my_shop_bot"}})
    )
    respx.post(f"{TELEGRAM_API_BASE}/bot111:validtoken/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )

    resp = await client.post(
        "/api/v1/integrations/telegram", json={"bot_token": "111:validtoken"}, headers=_auth(token)
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["platform"] == "telegram"
    assert body["external_bot_username"] == "my_shop_bot"
    assert body["status"] == "active"


@pytest.mark.asyncio
@respx.mock
async def test_connect_telegram_invalid_token_rejected(client: AsyncClient):
    token = await _register_and_login(client)

    respx.get(f"{TELEGRAM_API_BASE}/bot000:badtoken/getMe").mock(
        return_value=httpx.Response(200, json={"ok": False, "description": "Unauthorized"})
    )

    resp = await client.post(
        "/api/v1/integrations/telegram", json={"bot_token": "000:badtoken"}, headers=_auth(token)
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_connect_telegram_webhook_registration_failure_marks_error_status(client: AsyncClient):
    token = await _register_and_login(client)

    respx.get(f"{TELEGRAM_API_BASE}/bot222:token/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"id": 222, "username": "bot"}})
    )
    respx.post(f"{TELEGRAM_API_BASE}/bot222:token/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": False, "description": "bad webhook url"})
    )

    resp = await client.post(
        "/api/v1/integrations/telegram", json={"bot_token": "222:token"}, headers=_auth(token)
    )
    assert resp.status_code == 502


@pytest.mark.asyncio
@respx.mock
async def test_reconnecting_reuses_existing_integration_row(client: AsyncClient):
    token = await _register_and_login(client)

    respx.get(f"{TELEGRAM_API_BASE}/bot333:token/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"id": 333, "username": "bot_v1"}})
    )
    respx.post(f"{TELEGRAM_API_BASE}/bot333:token/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    first = await client.post(
        "/api/v1/integrations/telegram", json={"bot_token": "333:token"}, headers=_auth(token)
    )

    respx.get(f"{TELEGRAM_API_BASE}/bot333:tokenv2/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"id": 333, "username": "bot_v2"}})
    )
    respx.post(f"{TELEGRAM_API_BASE}/bot333:tokenv2/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    second = await client.post(
        "/api/v1/integrations/telegram", json={"bot_token": "333:tokenv2"}, headers=_auth(token)
    )

    assert first.json()["id"] == second.json()["id"]  # same row updated, not duplicated
    assert second.json()["external_bot_username"] == "bot_v2"

    list_resp = await client.get("/api/v1/integrations", headers=_auth(token))
    assert len(list_resp.json()) == 1


@pytest.mark.asyncio
@respx.mock
async def test_disconnect_telegram(client: AsyncClient):
    token = await _register_and_login(client)

    respx.get(f"{TELEGRAM_API_BASE}/bot444:token/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"id": 444, "username": "bot"}})
    )
    respx.post(f"{TELEGRAM_API_BASE}/bot444:token/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    await client.post("/api/v1/integrations/telegram", json={"bot_token": "444:token"}, headers=_auth(token))

    respx.post(f"{TELEGRAM_API_BASE}/bot444:token/deleteWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    resp = await client.delete("/api/v1/integrations/telegram", headers=_auth(token))
    assert resp.status_code == 204

    list_resp = await client.get("/api/v1/integrations", headers=_auth(token))
    assert list_resp.json() == []


@pytest.mark.asyncio
async def test_integrations_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/integrations")
    assert resp.status_code == 401


# ==================== WhatsApp ====================

from app.config import settings as _settings  # noqa: E402
from app.services.platforms.whatsapp_adapter import GRAPH_API_BASE  # noqa: E402

WA_API = f"{GRAPH_API_BASE}/{_settings.META_GRAPH_API_VERSION}"


def _mock_phone_number_info(phone_number_id: str, **overrides):
    body = {
        "verified_name": "Acme Mugs",
        "display_phone_number": "+1 555 0100",
        "quality_rating": "GREEN",
        "messaging_limit_tier": "TIER_1K",
        **overrides,
    }
    respx.get(f"{WA_API}/{phone_number_id}").mock(return_value=httpx.Response(200, json=body))


@pytest.mark.asyncio
@respx.mock
async def test_connect_whatsapp_manual_success(client: AsyncClient):
    token = await _register_and_login(client)
    _mock_phone_number_info("1111111111")
    respx.post(f"{WA_API}/waba-1/subscribed_apps").mock(return_value=httpx.Response(200, json={"success": True}))

    resp = await client.post(
        "/api/v1/integrations/whatsapp/manual",
        json={
            "business_account_id": "waba-1",
            "phone_number_id": "1111111111",
            "access_token": "EAAtoken",
            "verify_token": "my-verify-token",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["platform"] == "whatsapp"
    assert body["status"] == "active"

    profile_resp = await client.get("/api/v1/integrations/whatsapp/profile", headers=_auth(token))
    assert profile_resp.status_code == 200
    profile = profile_resp.json()
    assert profile["whatsapp_business_account_id"] == "waba-1"
    assert profile["business_name"] == "Acme Mugs"
    assert profile["quality_rating"] == "GREEN"


@pytest.mark.asyncio
@respx.mock
async def test_connect_whatsapp_manual_invalid_token_rejected(client: AsyncClient):
    token = await _register_and_login(client)
    respx.get(f"{WA_API}/2222222222").mock(
        return_value=httpx.Response(400, json={"error": {"message": "Invalid OAuth access token"}})
    )
    resp = await client.post(
        "/api/v1/integrations/whatsapp/manual",
        json={
            "business_account_id": "waba-2",
            "phone_number_id": "2222222222",
            "access_token": "badtoken",
            "verify_token": "vt",
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400


@pytest.mark.asyncio
@respx.mock
async def test_test_whatsapp_connection_does_not_persist_anything(client: AsyncClient):
    token = await _register_and_login(client)
    _mock_phone_number_info("3333333333")

    resp = await client.post(
        "/api/v1/integrations/whatsapp/test",
        json={"phone_number_id": "3333333333", "access_token": "EAAtoken"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert resp.json()["verified_name"] == "Acme Mugs"

    list_resp = await client.get("/api/v1/integrations", headers=_auth(token))
    assert list_resp.json() == []  # test-connection never saves anything


@pytest.mark.asyncio
@respx.mock
async def test_sync_whatsapp_refreshes_profile(client: AsyncClient):
    token = await _register_and_login(client)
    _mock_phone_number_info("4444444444")
    respx.post(f"{WA_API}/waba-4/subscribed_apps").mock(return_value=httpx.Response(200, json={"success": True}))
    await client.post(
        "/api/v1/integrations/whatsapp/manual",
        json={
            "business_account_id": "waba-4",
            "phone_number_id": "4444444444",
            "access_token": "EAAtoken",
            "verify_token": "vt",
        },
        headers=_auth(token),
    )

    respx.get(f"{WA_API}/4444444444").mock(
        return_value=httpx.Response(
            200,
            json={
                "verified_name": "Acme Mugs",
                "display_phone_number": "+1 555 0100",
                "quality_rating": "YELLOW",
                "messaging_limit_tier": "TIER_10K",
            },
        )
    )
    sync_resp = await client.post("/api/v1/integrations/whatsapp/sync", headers=_auth(token))
    assert sync_resp.status_code == 200
    assert sync_resp.json()["quality_rating"] == "YELLOW"
    assert sync_resp.json()["messaging_tier"] == "TIER_10K"


@pytest.mark.asyncio
@respx.mock
async def test_disconnect_whatsapp(client: AsyncClient):
    token = await _register_and_login(client)
    _mock_phone_number_info("5555555555")
    respx.post(f"{WA_API}/waba-5/subscribed_apps").mock(return_value=httpx.Response(200, json={"success": True}))
    await client.post(
        "/api/v1/integrations/whatsapp/manual",
        json={
            "business_account_id": "waba-5",
            "phone_number_id": "5555555555",
            "access_token": "EAAtoken",
            "verify_token": "vt",
        },
        headers=_auth(token),
    )

    resp = await client.delete("/api/v1/integrations/whatsapp", headers=_auth(token))
    assert resp.status_code == 204

    list_resp = await client.get("/api/v1/integrations", headers=_auth(token))
    assert list_resp.json() == []


@pytest.mark.asyncio
@respx.mock
async def test_connect_whatsapp_oauth_callback(client: AsyncClient):
    token = await _register_and_login(client)

    respx.get(f"{WA_API}/oauth/access_token").mock(
        return_value=httpx.Response(200, json={"access_token": "long-lived-token"})
    )
    respx.get(f"{WA_API}/me/businesses").mock(return_value=httpx.Response(200, json={"data": [{"id": "biz-1"}]}))
    respx.get(f"{WA_API}/biz-1/owned_whatsapp_business_accounts").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "waba-9"}]})
    )
    respx.get(f"{WA_API}/waba-9/phone_numbers").mock(
        return_value=httpx.Response(
            200, json={"data": [{"id": "6666666666", "display_phone_number": "+1 555 9999", "verified_name": "Acme"}]}
        )
    )
    _mock_phone_number_info("6666666666", verified_name="Acme")
    respx.post(f"{WA_API}/waba-9/subscribed_apps").mock(return_value=httpx.Response(200, json={"success": True}))

    resp = await client.post(
        "/api/v1/integrations/whatsapp/oauth/callback", json={"code": "meta-auth-code"}, headers=_auth(token)
    )
    assert resp.status_code == 201
    assert resp.json()["platform"] == "whatsapp"


@pytest.mark.asyncio
async def test_whatsapp_oauth_config_has_no_secrets(client: AsyncClient):
    token = await _register_and_login(client)
    resp = await client.get("/api/v1/integrations/whatsapp/oauth/config", headers=_auth(token))
    assert resp.status_code == 200
    assert "app_id" in resp.json()
    assert "secret" not in str(resp.json()).lower()


@pytest.mark.asyncio
@respx.mock
async def test_update_and_read_whatsapp_settings(client: AsyncClient):
    token = await _register_and_login(client)
    _mock_phone_number_info("7777777777")
    respx.post(f"{WA_API}/waba-7/subscribed_apps").mock(return_value=httpx.Response(200, json={"success": True}))
    await client.post(
        "/api/v1/integrations/whatsapp/manual",
        json={
            "business_account_id": "waba-7",
            "phone_number_id": "7777777777",
            "access_token": "EAAtoken",
            "verify_token": "vt",
        },
        headers=_auth(token),
    )

    patch_resp = await client.patch(
        "/api/v1/integrations/whatsapp/settings", json={"auto_reply": False, "typing_indicator": True}, headers=_auth(token)
    )
    assert patch_resp.status_code == 200
    assert patch_resp.json()["settings"]["auto_reply"] is False
    assert patch_resp.json()["settings"]["typing_indicator"] is True

    get_resp = await client.get("/api/v1/integrations/whatsapp/settings", headers=_auth(token))
    assert get_resp.json()["settings"]["auto_reply"] is False

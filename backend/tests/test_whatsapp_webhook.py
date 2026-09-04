import hashlib
import hmac
import json

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.models.user import User
from app.config import settings
from app.models.whatsapp_profile import WhatsAppBusinessProfile
from app.services.ai.base import AIProvider
from app.services.knowledge.storage import LocalStorageBackend
from app.services.platforms.whatsapp_adapter import WhatsAppAdapter

USER = {
    "email": "whatsapp-owner@example.com",
    "password": "StrongPass1",
    "full_name": "WhatsApp Owner",
    "business_name": "WhatsApp Co",
}
PHONE_NUMBER_ID = "1234567890"
APP_SECRET = "test-meta-app-secret"


class FakeProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "Thanks for reaching out — here's the answer to your question."

    async def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    async def summarize(self, text, max_words=None):
        return "summary"

    async def classify(self, text, labels):
        return labels[0]


class RecordingWhatsAppAdapter(WhatsAppAdapter):
    def __init__(self):
        super().__init__(phone_number_id=PHONE_NUMBER_ID, access_token="fake-token")
        self.sent: list[tuple[str, str]] = []
        self.marked_read: list[str] = []

    async def send_text(self, external_conversation_id, text):
        self.sent.append((external_conversation_id, text))

    async def mark_read(self, external_message_id, show_typing=False):
        self.marked_read.append(external_message_id)


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _create_integration(db_session: AsyncSession, settings_patch: dict | None = None) -> PlatformIntegration:
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(
        owner_id=user.id, platform=Platform.WHATSAPP, webhook_secret="unused-for-whatsapp",
        settings=settings_patch or {},
    )
    integration.set_credentials(
        {"phone_number_id": PHONE_NUMBER_ID, "access_token": "fake-token", "verify_token": "my-verify-token"}
    )
    db_session.add(integration)
    await db_session.flush()

    profile = WhatsAppBusinessProfile(
        integration_id=integration.id, whatsapp_business_account_id="waba1", phone_number_id=PHONE_NUMBER_ID
    )
    db_session.add(profile)
    await db_session.commit()
    await db_session.refresh(integration)
    return integration


@pytest.fixture
def wire_fakes(monkeypatch, tmp_path):
    fake_provider = FakeProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: fake_provider)
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: fake_provider)
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: fake_provider)
    monkeypatch.setattr(
        "app.services.knowledge.service.get_storage_backend",
        lambda: LocalStorageBackend(base_dir=str(tmp_path)),
    )
    adapter = RecordingWhatsAppAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)
    monkeypatch.setattr(settings, "META_APP_SECRET", APP_SECRET)
    return adapter


def _sign(body: bytes) -> str:
    digest = hmac.new(APP_SECRET.encode("utf-8"), body, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _text_payload(text: str, from_number: str = "234801", message_id: str = "wamid.1", name: str = "Customer") -> dict:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "contacts": [{"profile": {"name": name}}],
                            "messages": [{"from": from_number, "id": message_id, "type": "text", "text": {"body": text}}],
                        }
                    }
                ]
            }
        ]
    }


# ---------- GET verification ----------

@pytest.mark.asyncio
async def test_verify_webhook_with_app_level_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_VERIFY_TOKEN", "app-token")
    resp = await client.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "app-token", "hub.challenge": "12345"},
    )
    assert resp.status_code == 200
    assert resp.text == "12345"


@pytest.mark.asyncio
async def test_verify_webhook_with_per_integration_token(client: AsyncClient, db_session: AsyncSession, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_VERIFY_TOKEN", "")
    await _register_and_login(client)
    await _create_integration(db_session)

    resp = await client.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "my-verify-token", "hub.challenge": "abc"},
    )
    assert resp.status_code == 200
    assert resp.text == "abc"


@pytest.mark.asyncio
async def test_verify_webhook_rejects_wrong_token(client: AsyncClient, monkeypatch):
    monkeypatch.setattr(settings, "WHATSAPP_APP_VERIFY_TOKEN", "app-token")
    resp = await client.get(
        "/api/v1/whatsapp/webhook",
        params={"hub.mode": "subscribe", "hub.verify_token": "wrong", "hub.challenge": "12345"},
    )
    assert resp.status_code == 403


# ---------- POST events ----------

@pytest.mark.asyncio
async def test_webhook_rejects_missing_signature(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    await _register_and_login(client)
    await _create_integration(db_session)
    resp = await client.post("/api/v1/whatsapp/webhook", json=_text_payload("hi"))
    assert resp.status_code == 204
    assert wire_fakes.sent == []  # rejected before reaching the pipeline


@pytest.mark.asyncio
async def test_webhook_rejects_bad_signature(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    await _register_and_login(client)
    await _create_integration(db_session)
    resp = await client.post(
        "/api/v1/whatsapp/webhook", json=_text_payload("hi"), headers={"X-Hub-Signature-256": "sha256=deadbeef"}
    )
    assert resp.status_code == 204
    assert wire_fakes.sent == []


@pytest.mark.asyncio
async def test_webhook_full_round_trip(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    token = await _register_and_login(client)
    await _create_integration(db_session)
    adapter = wire_fakes

    body = json.dumps(_text_payload("How much for the website package?")).encode("utf-8")
    resp = await client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1
    chat_id, reply_text = adapter.sent[0]
    assert chat_id == "234801"
    assert "answer" in reply_text.lower()
    assert adapter.marked_read == ["wamid.1"]

    conversations = (await client.get("/api/v1/conversations", headers=_auth(token))).json()
    assert len(conversations) == 1
    assert conversations[0]["external_conversation_id"] == "234801"


@pytest.mark.asyncio
async def test_webhook_unknown_phone_number_id_is_a_noop(client: AsyncClient, wire_fakes):
    body = json.dumps(_text_payload("hi")).encode("utf-8")
    resp = await client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 204
    assert wire_fakes.sent == []


@pytest.mark.asyncio
async def test_webhook_status_update_is_a_noop(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    await _register_and_login(client)
    await _create_integration(db_session)
    payload = {
        "entry": [
            {"changes": [{"value": {"metadata": {"phone_number_id": PHONE_NUMBER_ID}, "statuses": [{"status": "read"}]}}]}
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    resp = await client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 204
    assert wire_fakes.sent == []


@pytest.mark.asyncio
async def test_interactive_button_reply_flows_through_router(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    token = await _register_and_login(client)
    await _create_integration(db_session)
    adapter = wire_fakes

    payload = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": PHONE_NUMBER_ID},
                            "messages": [
                                {
                                    "from": "234801",
                                    "id": "wamid.btn",
                                    "type": "interactive",
                                    "interactive": {
                                        "type": "button_reply",
                                        "button_reply": {"id": "confirm_order", "title": "Yes, confirm"},
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }
    body = json.dumps(payload).encode("utf-8")
    resp = await client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1  # went through the AI reply path, not the non-text acknowledgement path


@pytest.mark.asyncio
async def test_auto_reply_disabled_stores_message_without_replying(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    token = await _register_and_login(client)
    await _create_integration(db_session, settings_patch={"auto_reply": False})
    adapter = wire_fakes

    body = json.dumps(_text_payload("hello")).encode("utf-8")
    resp = await client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 204
    assert adapter.sent == []

    conversations = (await client.get("/api/v1/conversations", headers=_auth(token))).json()
    assert len(conversations) == 1  # message still stored


@pytest.mark.asyncio
async def test_business_hours_after_hours_sends_canned_reply_without_ai(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    from app.services.ai.base import AIProvider as _Base

    class ExplodingProvider(_Base):
        name = "exploding"

        async def generate(self, *a, **kw):
            raise AssertionError("AI should not be called outside business hours")

        async def embed(self, texts):
            raise AssertionError

        async def summarize(self, *a, **kw):
            raise AssertionError

        async def classify(self, *a, **kw):
            raise AssertionError

    exploding = ExplodingProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: exploding)
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: exploding)
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: exploding)
    monkeypatch.setattr(
        "app.services.knowledge.service.get_storage_backend", lambda: LocalStorageBackend(base_dir=str(tmp_path))
    )
    adapter = RecordingWhatsAppAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)
    monkeypatch.setattr(settings, "META_APP_SECRET", APP_SECRET)

    token = await _register_and_login(client)
    # A window that can never contain "now" -> always closed.
    await _create_integration(
        db_session,
        settings_patch={
            "business_hours": {
                "enabled": True,
                "timezone": "UTC",
                "hours": {},  # every day omitted -> closed all day, every day
                "message": "We're closed right now, we'll reply soon!",
            }
        },
    )

    body = json.dumps(_text_payload("hello")).encode("utf-8")
    resp = await client.post(
        "/api/v1/whatsapp/webhook",
        content=body,
        headers={"Content-Type": "application/json", "X-Hub-Signature-256": _sign(body)},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1
    assert "closed" in adapter.sent[0][1].lower()

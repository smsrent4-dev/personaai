import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.platforms.telegram_adapter import TelegramAdapter

USER = {
    "email": "viewer-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Viewer Owner",
    "business_name": "Viewer Co",
}
WEBHOOK_SECRET = "viewer-test-secret"


class RecordingTelegramAdapter(TelegramAdapter):
    def __init__(self):
        super().__init__(bot_token="fake:token")
        self.sent: list[tuple[str, str]] = []

    async def send_text(self, external_conversation_id, text):
        self.sent.append((external_conversation_id, text))


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _seed_conversation(client: AsyncClient, db_session, monkeypatch, tmp_path, text="Hello") -> tuple[str, str]:
    from app.services.ai.base import AIProvider
    from app.services.knowledge.storage import LocalStorageBackend

    class FakeProvider(AIProvider):
        name = "fake"

        async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
            return "auto reply"

        async def embed(self, texts):
            return [[0.1, 0.2] for _ in texts]

        async def summarize(self, text, max_words=None):
            return "summary"

        async def classify(self, text, labels):
            return labels[0]

    token = await _register_and_login(client)

    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()

    fake = FakeProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: fake)
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: fake)
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: fake)
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: fake)
    monkeypatch.setattr(
        "app.services.knowledge.service.get_storage_backend",
        lambda: LocalStorageBackend(base_dir=str(tmp_path)),
    )
    pipeline_adapter = RecordingTelegramAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: pipeline_adapter)

    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "username": "customer", "first_name": "Cust"},
            "chat": {"id": 777},
            "text": text,
        }
    }
    await client.post(
        f"/api/v1/telegram/webhook/{WEBHOOK_SECRET}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
    )

    conversations = (await client.get("/api/v1/conversations", headers=_auth(token))).json()
    return token, conversations[0]["id"]


@pytest.mark.asyncio
async def test_set_tags(client: AsyncClient, db_session, monkeypatch, tmp_path):
    token, conv_id = await _seed_conversation(client, db_session, monkeypatch, tmp_path)
    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/tags", json={"tags": ["vip", "billing"]}, headers=_auth(token)
    )
    assert resp.status_code == 200
    assert set(resp.json()["tags"]) == {"vip", "billing"}


@pytest.mark.asyncio
async def test_takeover_stops_auto_reply(client: AsyncClient, db_session, monkeypatch, tmp_path):
    token, conv_id = await _seed_conversation(client, db_session, monkeypatch, tmp_path)

    takeover_resp = await client.post(f"/api/v1/conversations/{conv_id}/takeover", headers=_auth(token))
    assert takeover_resp.json()["assigned_to_human"] is True

    before = (await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=_auth(token))).json()

    payload = {
        "message": {
            "message_id": 2,
            "from": {"id": 1, "username": "customer", "first_name": "Cust"},
            "chat": {"id": 777},
            "text": "Are you still there?",
        }
    }
    await client.post(
        f"/api/v1/telegram/webhook/{WEBHOOK_SECRET}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
    )

    after = (await client.get(f"/api/v1/conversations/{conv_id}/messages", headers=_auth(token))).json()
    assert len(after) == len(before) + 1
    assert after[-1]["role"] == "user"


@pytest.mark.asyncio
async def test_human_send_message_after_takeover(client: AsyncClient, db_session, monkeypatch, tmp_path):
    token, conv_id = await _seed_conversation(client, db_session, monkeypatch, tmp_path)
    await client.post(f"/api/v1/conversations/{conv_id}/takeover", headers=_auth(token))

    human_adapter = RecordingTelegramAdapter()
    monkeypatch.setattr("app.services.human_reply_service.build_adapter", lambda integration: human_adapter)

    resp = await client.post(
        f"/api/v1/conversations/{conv_id}/messages",
        json={"content": "I'm here, how can I help?"},
        headers=_auth(token),
    )
    assert resp.status_code == 200
    assert resp.json()["role"] == "agent"
    assert resp.json()["agent_id"] is None
    assert human_adapter.sent == [("777", "I'm here, how can I help?")]


@pytest.mark.asyncio
async def test_release_hands_back_to_ai(client: AsyncClient, db_session, monkeypatch, tmp_path):
    token, conv_id = await _seed_conversation(client, db_session, monkeypatch, tmp_path)
    await client.post(f"/api/v1/conversations/{conv_id}/takeover", headers=_auth(token))
    resp = await client.post(f"/api/v1/conversations/{conv_id}/release", headers=_auth(token))
    assert resp.json()["assigned_to_human"] is False


@pytest.mark.asyncio
async def test_export_conversation_csv(client: AsyncClient, db_session, monkeypatch, tmp_path):
    token, conv_id = await _seed_conversation(client, db_session, monkeypatch, tmp_path, text="Export me")
    resp = await client.get(f"/api/v1/conversations/{conv_id}/export", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/csv")
    assert "Export me" in resp.text
    assert resp.text.startswith("timestamp,role,message_type,content")


@pytest.mark.asyncio
async def test_filter_conversations_by_search(client: AsyncClient, db_session, monkeypatch, tmp_path):
    token, conv_id = await _seed_conversation(client, db_session, monkeypatch, tmp_path)

    match = await client.get("/api/v1/conversations?search=customer", headers=_auth(token))
    assert len(match.json()) == 1

    no_match = await client.get("/api/v1/conversations?search=nonexistent", headers=_auth(token))
    assert len(no_match.json()) == 0

import pytest
from httpx import AsyncClient

from app.services.ai.base import AIProvider
from app.services.knowledge.storage import LocalStorageBackend
from app.services.platforms.telegram_adapter import TelegramAdapter

USER = {
    "email": "notif-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Notif Owner",
    "business_name": "Notif Co",
}
WEBHOOK_SECRET = "notif-test-secret"


class FakeProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "reply"

    async def embed(self, texts):
        return [[0.1, 0.2] for _ in texts]

    async def summarize(self, text, max_words=None):
        return "summary"

    async def classify(self, text, labels):
        return labels[0]


class RecordingTelegramAdapter(TelegramAdapter):
    def __init__(self):
        super().__init__(bot_token="fake:token")
        self.sent = []

    async def send_text(self, external_conversation_id, text):
        self.sent.append((external_conversation_id, text))


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_new_conversation_creates_a_lead_notification(client: AsyncClient, db_session, monkeypatch, tmp_path):
    from sqlalchemy import select
    from app.models.integration import PlatformIntegration
    from app.models.platform_enums import Platform
    from app.models.user import User

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
    adapter = RecordingTelegramAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)

    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "username": "lead_customer", "first_name": "Lead"},
            "chat": {"id": 42},
            "text": "Hi, interested in your services",
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{WEBHOOK_SECRET}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": WEBHOOK_SECRET},
    )
    assert resp.status_code == 204

    notif_resp = await client.get("/api/v1/notifications", headers=_auth(token))
    notifications = notif_resp.json()
    assert any(n["type"] == "new_lead" for n in notifications)


@pytest.mark.asyncio
async def test_unread_count_zero_on_fresh_account(client: AsyncClient):
    token = await _register_and_login(client)
    count_resp = await client.get("/api/v1/notifications/unread-count", headers=_auth(token))
    assert count_resp.status_code == 200
    assert count_resp.json()["count"] == 0


@pytest.mark.asyncio
async def test_notifications_require_auth(client: AsyncClient):
    resp = await client.get("/api/v1/notifications")
    assert resp.status_code == 401

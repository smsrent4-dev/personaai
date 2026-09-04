import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.ai.base import AIProvider
from app.services.knowledge.storage import LocalStorageBackend
from app.services.platforms.telegram_adapter import TelegramAdapter

USER = {
    "email": "photo-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Photo Owner",
    "business_name": "Photo Co",
}
WEBHOOK_SECRET = "photo-test-secret"
_KEYWORDS = ["shirt", "shoes", "hat"]


class FakeProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "Here's what I found for you."

    async def embed(self, texts):
        return [[1.0 if kw in t.lower() else 0.0 for kw in _KEYWORDS] for t in texts]

    async def summarize(self, text, max_words=None):
        return "summary"

    async def classify(self, text, labels):
        return labels[0]


class RecordingTelegramAdapter(TelegramAdapter):
    def __init__(self):
        super().__init__(bot_token="fake:token")
        self.sent_text: list[tuple[str, str]] = []
        self.sent_photos: list[tuple[str, str, str | None]] = []

    async def send_text(self, external_conversation_id, text):
        self.sent_text.append((external_conversation_id, text))

    async def send_photo(self, external_conversation_id, image_url, caption=None):
        self.sent_photos.append((external_conversation_id, image_url, caption))


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def wire_fakes(monkeypatch, tmp_path):
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
    return adapter


async def _create_integration(client: AsyncClient, db_session) -> PlatformIntegration:
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()
    await db_session.refresh(integration)
    return integration


def _payload(text: str, chat_id: int = 555) -> dict:
    return {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "username": "customer", "first_name": "Cust"},
            "chat": {"id": chat_id},
            "text": text,
        }
    }


@pytest.mark.asyncio
async def test_strongly_matching_product_sends_photo_before_text(client: AsyncClient, db_session, wire_fakes):
    token = await _register_and_login(client)
    integration = await _create_integration(client, db_session)

    create_resp = await client.post(
        "/api/v1/products",
        json={
            "name": "Blue Shirt",
            "product_type": "physical",
            "price": "20.00",
            "images": ["https://example.com/blue-shirt.jpg"],
        },
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_payload("Do you have a shirt?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204

    adapter = wire_fakes
    assert len(adapter.sent_photos) == 1
    chat_id, image_url, caption = adapter.sent_photos[0]
    assert chat_id == "555"
    assert image_url == "https://example.com/blue-shirt.jpg"
    assert "Blue Shirt" in caption
    assert len(adapter.sent_text) == 1


@pytest.mark.asyncio
async def test_weakly_matching_product_does_not_send_photo(client: AsyncClient, db_session, wire_fakes):
    token = await _register_and_login(client)
    integration = await _create_integration(client, db_session)

    create_resp = await client.post(
        "/api/v1/products",
        json={
            "name": "Blue Shirt",
            "product_type": "physical",
            "price": "20.00",
            "images": ["https://example.com/blue-shirt.jpg"],
        },
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_payload("What time do you close today?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204

    adapter = wire_fakes
    assert adapter.sent_photos == []
    assert len(adapter.sent_text) == 1


@pytest.mark.asyncio
async def test_matching_product_without_images_sends_no_photo(client: AsyncClient, db_session, wire_fakes):
    token = await _register_and_login(client)
    integration = await _create_integration(client, db_session)

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Sun Hat", "product_type": "physical", "price": "15.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_payload("Do you sell hats?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204

    adapter = wire_fakes
    assert adapter.sent_photos == []


@pytest.mark.asyncio
async def test_product_photo_caption_includes_sizes_and_stock(client: AsyncClient, db_session, wire_fakes):
    """The actual reported gap: a caption used to be just name+price —
    a customer asking "do you have crocs?" had no way to see what sizes
    or colors were actually available, or whether it was in stock."""
    token = await _register_and_login(client)
    integration = await _create_integration(client, db_session)

    create_resp = await client.post(
        "/api/v1/products",
        json={
            "name": "Crocs Shoes",
            "product_type": "physical",
            "price": "20.00",
            "inventory": 12,
            "images": ["https://example.com/crocs.jpg"],
            "variants": [{"name": "Size 40, Black"}, {"name": "Size 42, Red"}],
        },
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_payload("Do you have shoes?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204

    adapter = wire_fakes
    assert len(adapter.sent_photos) == 1
    _chat_id, _image_url, caption = adapter.sent_photos[0]
    assert "Size 40, Black" in caption
    assert "Size 42, Red" in caption
    assert "In stock" in caption

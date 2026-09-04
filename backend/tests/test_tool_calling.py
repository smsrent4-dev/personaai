import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.models.integration import PlatformIntegration
from app.models.order import Order
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.ai.base import AIProvider, ToolDefinition, ToolExecutor
from app.services.knowledge.storage import LocalStorageBackend
from app.services.platforms.telegram_adapter import TelegramAdapter

USER = {
    "email": "tool-owner@example.com", "password": "StrongPass1",
    "full_name": "Tool Owner", "business_name": "Tool Co",
}
WEBHOOK_SECRET = "tool-test-secret"
_KEYWORDS = ["hoodie"]


class FakeEmbeddingProvider(AIProvider):
    name = "fake"

    async def generate(self, prompt, system_instruction=None, temperature=0.7, max_tokens=None):
        return "plain reply, no tools used"

    async def embed(self, texts):
        return [[1.0 if kw in t.lower() else 0.0 for kw in _KEYWORDS] for t in texts]

    async def summarize(self, text, max_words=None):
        return "summary"

    async def classify(self, text, labels):
        return labels[0]


class FakeToolCallingProvider(FakeEmbeddingProvider):
    """Simulates a model that decides, on its own, to search for the
    product the customer asked about and then place the order - this is
    the fake-provider equivalent of what GeminiProvider.generate_with_tools
    does for real against Gemini's function-calling API. We don't need to
    fake Gemini's wire format here; we're testing that MessagingPipeline
    wires ToolContext/execute_tool correctly, which is provider-agnostic."""

    async def generate_with_tools(
        self,
        prompt: str,
        tools: list[ToolDefinition],
        tool_executor: ToolExecutor,
        system_instruction: str | None = None,
        temperature: float = 0.7,
        max_tool_iterations: int = 3,
    ) -> str:
        search_result = await tool_executor("search_product", {"query": "hoodie"})
        products = search_result.get("products", [])
        if not products:
            return "Sorry, I couldn't find that product."

        product = products[0]
        order_result = await tool_executor(
            "create_order",
            {
                "items": [{"product_id": product["id"], "quantity": 2}],
                "recipient_name": "Test Recipient",
                "shipping_address": "123 Test St, Lagos",
            },
        )
        if "error" in order_result:
            return f"Something went wrong placing your order: {order_result['error']}"

        return (
            f"Done! I've placed your order for 2x {product['name']} - "
            f"total {order_result['total_amount']} {order_result['currency']}. "
            f"Order ID {order_result['order_id']}."
        )


class RecordingTelegramAdapter(TelegramAdapter):
    def __init__(self):
        super().__init__(bot_token="fake:token")
        self.sent_text: list[tuple[str, str]] = []

    async def send_text(self, external_conversation_id, text):
        self.sent_text.append((external_conversation_id, text))


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_ai_searches_product_and_creates_order_via_tool_calling(
    client: AsyncClient, db_session, monkeypatch, tmp_path
):
    token = await _register_and_login(client)

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Classic Hoodie", "product_type": "physical", "price": "25.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()

    fake = FakeToolCallingProvider()
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
            "from": {"id": 777, "username": "shopper", "first_name": "Shopper"},
            "chat": {"id": 888},
            "text": "I want to order two hoodies please",
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204

    order_result = await db_session.execute(select(Order).where(Order.owner_id == user.id))
    orders = order_result.scalars().all()
    assert len(orders) == 1
    assert orders[0].items[0]["quantity"] == 2
    assert orders[0].total_amount == 50

    assert len(adapter.sent_text) == 1
    assert "Order ID" in adapter.sent_text[0][1]

    orders_resp = await client.get("/api/v1/orders", headers=_auth(token))
    assert len(orders_resp.json()) == 1


@pytest.mark.asyncio
async def test_ai_gets_a_clean_error_when_stock_is_insufficient(
    client: AsyncClient, db_session, monkeypatch, tmp_path
):
    """The tool loop shouldn't crash on a 409 from create_order — it
    should feed a clean error back to the model so it can tell the
    customer, same as any other tool_executor error path."""
    token = await _register_and_login(client)

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Classic Hoodie", "product_type": "physical", "price": "25.00", "inventory": 1},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()

    fake = FakeToolCallingProvider()
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
            "from": {"id": 42, "username": "shopper", "first_name": "Shopper"},
            "chat": {"id": 43},
            "text": "I want to order two hoodies please",  # only 1 in stock
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204

    assert len(adapter.sent_text) == 1
    assert "went wrong" in adapter.sent_text[0][1].lower()

    order_result = await db_session.execute(select(Order).where(Order.owner_id == user.id))
    assert order_result.scalars().all() == []  # no partial order left behind

    product_resp = await client.get(f"/api/v1/products/{product_id}", headers=_auth(token))
    assert product_resp.json()["inventory"] == 1  # untouched


@pytest.mark.asyncio
async def test_ai_gets_a_clean_error_for_a_physical_order_missing_delivery_details(
    client: AsyncClient, db_session, monkeypatch, tmp_path
):
    """If the AI calls create_order for a physical product without
    having collected recipient_name/shipping_address first (ignoring
    its own instructions, or just a model mistake), the tool must
    return a clean, actionable error rather than a raw exception or a
    silently-created unshippable order — same contract as the
    insufficient-stock case above."""
    token = await _register_and_login(client)

    create_resp = await client.post(
        "/api/v1/products",
        json={"name": "Classic Hoodie", "product_type": "physical", "price": "25.00"},
        headers=_auth(token),
    )
    product_id = create_resp.json()["id"]
    await client.patch(f"/api/v1/products/{product_id}", json={"status": "active"}, headers=_auth(token))

    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()

    class ForgetfulToolCallingProvider(FakeEmbeddingProvider):
        """Simulates the AI skipping straight to create_order without
        ever asking for delivery details — the failure mode the fix is
        actually guarding against."""

        async def generate_with_tools(self, prompt, tools, tool_executor, system_instruction=None, temperature=0.7, max_tool_iterations=3):
            search_result = await tool_executor("search_product", {"query": "hoodie"})
            product = search_result["products"][0]
            order_result = await tool_executor("create_order", {"items": [{"product_id": product["id"], "quantity": 1}]})
            if "error" in order_result:
                return f"I need a bit more info: {order_result['error']}"
            return "Order placed!"

    fake = ForgetfulToolCallingProvider()
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
            "from": {"id": 55, "username": "shopper", "first_name": "Shopper"},
            "chat": {"id": 56},
            "text": "I'll take a hoodie",
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert len(adapter.sent_text) == 1
    assert "shipping address" in adapter.sent_text[0][1].lower()

    order_result = await db_session.execute(select(Order).where(Order.owner_id == user.id))
    assert order_result.scalars().all() == []  # no unshippable order left behind


@pytest.mark.asyncio
async def test_no_customer_identity_skips_tool_calling_gracefully(
    client: AsyncClient, db_session, monkeypatch, tmp_path
):
    token = await _register_and_login(client)
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()

    fake = FakeToolCallingProvider()
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
            "from": {},
            "chat": {"id": 999},
            "text": "hello",
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert len(adapter.sent_text) == 1
    assert adapter.sent_text[0][1] == "plain reply, no tools used"

    order_result = await db_session.execute(select(Order).where(Order.owner_id == user.id))
    assert order_result.scalars().all() == []

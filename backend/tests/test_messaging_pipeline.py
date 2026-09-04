import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.ai.base import AIProvider
from app.services.knowledge.storage import LocalStorageBackend
from app.services.platforms.telegram_adapter import TelegramAdapter

USER = {
    "email": "pipeline-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Pipeline Owner",
    "business_name": "Pipeline Co",
}
WEBHOOK_SECRET = "test-webhook-secret-123"


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


async def _create_integration(db_session: AsyncSession) -> PlatformIntegration:
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(
        owner_id=user.id,
        platform=Platform.TELEGRAM,
        webhook_secret=WEBHOOK_SECRET,
    )
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
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
    adapter = RecordingTelegramAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)
    return adapter


def _text_payload(text: str, chat_id: int = 999, user_id: int = 555) -> dict:
    return {
        "message": {
            "message_id": 1,
            "from": {"id": user_id, "username": "customer", "first_name": "Cust"},
            "chat": {"id": chat_id},
            "text": text,
        }
    }


@pytest.mark.asyncio
async def test_webhook_generates_and_sends_a_reply(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    token = await _register_and_login(client)
    integration = await _create_integration(db_session)
    adapter = wire_fakes

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_text_payload("How much for the website package?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1
    chat_id, reply_text = adapter.sent[0]
    assert chat_id == "999"
    assert "answer" in reply_text.lower()

    conversations = (await client.get("/api/v1/conversations", headers=_auth(token))).json()
    assert len(conversations) == 1
    assert conversations[0]["external_conversation_id"] == "999"
    assert conversations[0]["external_user_name"] == "customer"

    messages = (
        await client.get(f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=_auth(token))
    ).json()
    assert len(messages) == 2
    assert messages[0]["role"] == "user"
    assert messages[0]["content"] == "How much for the website package?"
    assert messages[1]["role"] == "agent"
    assert messages[1]["agent_id"] is not None


@pytest.mark.asyncio
async def test_second_message_reuses_same_conversation(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    token = await _register_and_login(client)
    integration = await _create_integration(db_session)

    headers = {"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret}
    await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}", json=_text_payload("First message"), headers=headers
    )
    await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}", json=_text_payload("Second message"), headers=headers
    )

    conversations = (await client.get("/api/v1/conversations", headers=_auth(token))).json()
    assert len(conversations) == 1  # same chat_id -> same conversation, not duplicated

    messages = (
        await client.get(f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=_auth(token))
    ).json()
    assert len(messages) == 4  # 2 user + 2 agent


@pytest.mark.asyncio
async def test_webhook_rejects_wrong_secret_token_header(client: AsyncClient, db_session: AsyncSession, wire_fakes):
    await _register_and_login(client)
    integration = await _create_integration(db_session)
    adapter = wire_fakes

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_text_payload("hello"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "wrong-secret"},
    )
    assert resp.status_code == 204
    assert adapter.sent == []  # never reached the pipeline


@pytest.mark.asyncio
async def test_webhook_unknown_path_secret_is_a_silent_noop(client: AsyncClient, wire_fakes):
    resp = await client.post(
        "/api/v1/telegram/webhook/does-not-exist",
        json=_text_payload("hello"),
        headers={"X-Telegram-Bot-Api-Secret-Token": "does-not-exist"},
    )
    assert resp.status_code == 204
    assert wire_fakes.sent == []


@pytest.mark.asyncio
async def test_non_text_message_gets_generic_acknowledgement_without_calling_ai(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    class ExplodingProvider(AIProvider):
        name = "exploding"

        async def generate(self, *a, **kw):
            raise AssertionError("generate() should not be called for non-text messages")

        async def embed(self, texts):
            raise AssertionError("embed() should not be called for non-text messages")

        async def summarize(self, *a, **kw):
            raise AssertionError

        async def classify(self, *a, **kw):
            raise AssertionError

    exploding = ExplodingProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: exploding)
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: exploding)
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: exploding)
    monkeypatch.setattr(
        "app.services.knowledge.service.get_storage_backend",
        lambda: LocalStorageBackend(base_dir=str(tmp_path)),
    )
    adapter = RecordingTelegramAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)

    location_payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Bob"},
            "chat": {"id": 2},
            "location": {"latitude": 6.5, "longitude": 3.3},
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=location_payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1
    assert "location" in adapter.sent[0][1].lower()


# ---------- image/voice analysis (the "AI can't see or hear anything" fix) ----------


class RecordingAdapterWithMedia(RecordingTelegramAdapter):
    """Same recording behavior as RecordingTelegramAdapter, but with a
    fake download_media so tests don't need real Telegram file hosting."""

    def __init__(self, media_bytes: bytes = b"fake-bytes", media_mime: str = "image/jpeg"):
        super().__init__()
        self.media_bytes = media_bytes
        self.media_mime = media_mime
        self.download_calls: list[str] = []

    async def download_media(self, media_id: str) -> tuple[bytes, str]:
        self.download_calls.append(media_id)
        return self.media_bytes, self.media_mime


class FakeVisionProvider(FakeProvider):
    """Actually 'sees' and 'hears' — describe_image/transcribe_audio
    return canned-but-real values instead of the base class's
    not-supported fallback, so these tests exercise the real analysis
    path rather than the degrade-gracefully path."""

    name = "fake-vision"

    def __init__(self, image_description: str = "A product photo of a blue sneaker.", transcript: str = "Do you have this in size 42?", classification: str = "something_else"):
        self.image_description = image_description
        self.transcript = transcript
        self.classification = classification

    async def describe_image(self, image_bytes, mime_type, instruction=None):
        return self.image_description

    async def transcribe_audio(self, audio_bytes, mime_type):
        return self.transcript

    async def classify(self, text, labels):
        return self.classification if self.classification in labels else labels[-1]


def _photo_payload(chat_id: int = 999, user_id: int = 555, caption: str | None = None) -> dict:
    message = {
        "message_id": 1,
        "from": {"id": user_id, "username": "customer", "first_name": "Cust"},
        "chat": {"id": chat_id},
        "photo": [{"file_id": "photo-file-id", "file_size": 100}],
    }
    if caption:
        message["caption"] = caption
    return {"message": message}


def _voice_payload(chat_id: int = 999, user_id: int = 555) -> dict:
    return {
        "message": {
            "message_id": 1,
            "from": {"id": user_id, "username": "customer", "first_name": "Cust"},
            "chat": {"id": chat_id},
            "voice": {"file_id": "voice-file-id", "duration": 3},
        }
    }


def _wire_vision(monkeypatch, tmp_path, provider: FakeVisionProvider, adapter: RecordingAdapterWithMedia):
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: provider)
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: provider)
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: provider)
    monkeypatch.setattr(
        "app.services.knowledge.service.get_storage_backend",
        lambda: LocalStorageBackend(base_dir=str(tmp_path)),
    )
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)


@pytest.mark.asyncio
async def test_photo_of_a_product_gets_a_real_ai_reply_not_a_canned_ack(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    """The bug report, part 1: 'does this look like the one in the
    picture?' should get an actual answer, not 'thanks, I got that'."""
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    adapter = RecordingAdapterWithMedia()
    provider = FakeVisionProvider(image_description="A blue running shoe, size tag reads 42.")
    _wire_vision(monkeypatch, tmp_path, provider, adapter)

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_photo_payload(caption="does this look like the one in the picture?"),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert adapter.download_calls == ["photo-file-id"]  # the image was actually downloaded
    assert len(adapter.sent) == 1
    # Real reply from FakeProvider.generate(), not the canned IMAGE acknowledgement.
    assert "answer" in adapter.sent[0][1].lower()
    assert "thanks for the image" not in adapter.sent[0][1].lower()


@pytest.mark.asyncio
async def test_photo_of_a_product_backfills_conversation_history(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    """The stored inbound message should reflect what the photo showed,
    not sit there as a blank/None row forever."""
    token = await _register_and_login(client)
    integration = await _create_integration(db_session)

    adapter = RecordingAdapterWithMedia()
    provider = FakeVisionProvider(image_description="A blue running shoe, size tag reads 42.")
    _wire_vision(monkeypatch, tmp_path, provider, adapter)

    await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_photo_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )

    conversations = (await client.get("/api/v1/conversations", headers=_auth(token))).json()
    messages = (
        await client.get(f"/api/v1/conversations/{conversations[0]['id']}/messages", headers=_auth(token))
    ).json()
    assert "blue running shoe" in messages[0]["content"].lower()


@pytest.mark.asyncio
async def test_payment_screenshot_auto_attaches_to_awaiting_order_without_auto_confirming(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    """The bug report, part 2: a payment screenshot should actually
    reach the order — but must NOT silently mark it paid; that's still
    a human decision (OrderService.confirm_payment)."""
    from app.models.customer import Customer
    from app.models.order import Order, OrderStatus, PaymentStatus
    from app.models.platform_enums import Platform

    await _register_and_login(client)
    integration = await _create_integration(db_session)

    customer = Customer(owner_id=integration.owner_id, platform=Platform.TELEGRAM, external_user_id="555")
    db_session.add(customer)
    await db_session.flush()
    order = Order(
        owner_id=integration.owner_id,
        customer_id=customer.id,
        status=OrderStatus.PENDING,
        payment_status=PaymentStatus.UNPAID,
        items=[{"product_id": str(customer.id), "name": "Test item", "quantity": 1, "unit_price": "10.00"}],
        total_amount="10.00",
        currency="NGN",
    )
    db_session.add(order)
    await db_session.commit()
    await db_session.refresh(order)

    adapter = RecordingAdapterWithMedia()
    provider = FakeVisionProvider(
        image_description="A bank transfer receipt showing NGN 10,000 sent, ref TX-8842, status: successful.",
        classification="payment_receipt_or_bank_transfer_confirmation",
    )
    _wire_vision(monkeypatch, tmp_path, provider, adapter)

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_photo_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1
    assert "review and confirm" in adapter.sent[0][1].lower()

    await db_session.refresh(order)
    assert order.receipt_file_id == "photo-file-id"
    assert order.payment_status == PaymentStatus.AWAITING_CONFIRMATION  # NOT PaymentStatus.PAID
    assert order.status == OrderStatus.PENDING  # untouched — confirm_payment is a separate, human step


@pytest.mark.asyncio
async def test_voice_note_gets_transcribed_and_answered_like_text(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    adapter = RecordingAdapterWithMedia(media_bytes=b"fake-audio", media_mime="audio/ogg")
    provider = FakeVisionProvider(transcript="Do you deliver to Lekki?")
    _wire_vision(monkeypatch, tmp_path, provider, adapter)

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_voice_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert adapter.download_calls == ["voice-file-id"]
    assert len(adapter.sent) == 1
    assert "thanks for the voice message" not in adapter.sent[0][1].lower()


@pytest.mark.asyncio
async def test_image_download_failure_degrades_to_canned_acknowledgement(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, tmp_path
):
    """Vision analysis is an enhancement, not a new single point of
    failure — if the download or the AI call blows up, the customer
    still gets a reply."""
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    class BrokenDownloadAdapter(RecordingTelegramAdapter):
        async def download_media(self, media_id):
            raise RuntimeError("network blip")

    adapter = BrokenDownloadAdapter()
    provider = FakeVisionProvider()
    _wire_vision(monkeypatch, tmp_path, provider, adapter)

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=_photo_payload(),
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )
    assert resp.status_code == 204
    assert len(adapter.sent) == 1
    assert "thanks for the image" in adapter.sent[0][1].lower()


@pytest.mark.asyncio
async def test_ai_failure_during_reply_generation_sends_fallback_not_silence(
    client: AsyncClient, db_session: AsyncSession, monkeypatch
):
    """Regression test: previously, an exception during routing or reply
    generation (e.g. a missing/invalid GEMINI_API_KEY, quota exhausted,
    Gemini having an outage) propagated all the way out of
    handle_incoming uncaught — the customer got NO reply at all, with
    nothing indicating anything had gone wrong. Every other failure
    point in the pipeline (image analysis, message limits) already
    degrades to a sent fallback reply; this proves the actual
    reply-generation step does too, now."""
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    class BrokenAIProvider(AIProvider):
        name = "broken"

        async def generate(self, *a, **kw):
            raise RuntimeError("simulated: invalid or missing GEMINI_API_KEY")

        async def embed(self, texts):
            return [[0.1, 0.2, 0.3] for _ in texts]

        async def summarize(self, *a, **kw):
            return "summary"

        async def classify(self, text, labels):
            return labels[0]

    broken = BrokenAIProvider()
    monkeypatch.setattr("app.services.router_service.get_ai_provider", lambda: broken)
    monkeypatch.setattr("app.services.knowledge.service.get_ai_provider", lambda: broken)
    monkeypatch.setattr("app.services.memory_service.get_ai_provider", lambda: broken)
    monkeypatch.setattr("app.services.product_service.get_ai_provider", lambda: broken)
    adapter = RecordingTelegramAdapter()
    monkeypatch.setattr("app.services.messaging_pipeline.build_adapter", lambda integration: adapter)

    text_payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "username": "customer", "first_name": "Cust"},
            "chat": {"id": 2},
            "text": "hello, are you open?",
        }
    }
    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json=text_payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )

    # The webhook itself must still ack cleanly — an AI failure is not
    # a reason for Telegram to see an error and start retry-storming.
    assert resp.status_code == 204

    # The customer must have gotten SOMETHING, not silence.
    assert len(adapter.sent) == 1
    assert "went wrong" in adapter.sent[0][1].lower()

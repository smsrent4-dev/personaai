import httpx
import pytest
import respx

from app.models.message import MessageType
from app.services.platforms.telegram_adapter import TELEGRAM_API_BASE, TelegramAdapter, TelegramAPIError


def _adapter() -> TelegramAdapter:
    return TelegramAdapter(bot_token="123:ABC")


def test_parse_text_message():
    payload = {
        "message": {
            "message_id": 42,
            "from": {"id": 555, "username": "jane", "first_name": "Jane"},
            "chat": {"id": 999, "type": "private"},
            "text": "How much for the website package?",
        }
    }
    result = _adapter().parse_incoming(payload)
    assert result is not None
    assert result.message_type == MessageType.TEXT
    assert result.text == "How much for the website package?"
    assert result.external_conversation_id == "999"
    assert result.external_user_id == "555"
    assert result.external_user_name == "jane"
    assert result.external_message_id == "42"


def test_parse_photo_message_uses_largest_size_and_caption():
    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Bob"},
            "chat": {"id": 2},
            "photo": [{"file_id": "small"}, {"file_id": "large"}],
            "caption": "Check this out",
        }
    }
    result = _adapter().parse_incoming(payload)
    assert result.message_type == MessageType.IMAGE
    assert result.media_file_id == "large"
    assert result.text == "Check this out"


def test_parse_document_message():
    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Bob"},
            "chat": {"id": 2},
            "document": {"file_id": "doc123", "file_name": "invoice.pdf"},
        }
    }
    result = _adapter().parse_incoming(payload)
    assert result.message_type == MessageType.DOCUMENT
    assert result.media_file_id == "doc123"


def test_parse_voice_message():
    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Bob"},
            "chat": {"id": 2},
            "voice": {"file_id": "voice123"},
        }
    }
    result = _adapter().parse_incoming(payload)
    assert result.message_type == MessageType.VOICE
    assert result.media_file_id == "voice123"


def test_parse_location_message():
    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Bob"},
            "chat": {"id": 2},
            "location": {"latitude": 6.5244, "longitude": 3.3792},
        }
    }
    result = _adapter().parse_incoming(payload)
    assert result.message_type == MessageType.LOCATION
    assert result.latitude == 6.5244
    assert result.longitude == 3.3792


def test_parse_unrecognized_content_falls_back_to_other():
    payload = {
        "message": {
            "message_id": 1,
            "from": {"id": 1, "first_name": "Bob"},
            "chat": {"id": 2},
            "sticker": {"file_id": "sticker123"},
        }
    }
    result = _adapter().parse_incoming(payload)
    assert result.message_type == MessageType.OTHER


def test_parse_non_message_update_returns_none():
    payload = {"edited_message": {"message_id": 1, "chat": {"id": 2}, "text": "edited"}}
    assert _adapter().parse_incoming(payload) is None


@pytest.mark.asyncio
@respx.mock
async def test_send_text_success():
    route = respx.post(f"{TELEGRAM_API_BASE}/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}})
    )
    adapter = _adapter()
    await adapter.send_text("999", "Hello there")
    assert route.called
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_text_splits_long_messages():
    route = respx.post(f"{TELEGRAM_API_BASE}/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {}})
    )
    adapter = _adapter()
    await adapter.send_text("999", "x" * 9000)
    assert route.call_count == 3  # 9000 / 4096 rounds up to 3
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_text_raises_on_telegram_error():
    respx.post(f"{TELEGRAM_API_BASE}/bot123:ABC/sendMessage").mock(
        return_value=httpx.Response(200, json={"ok": False, "description": "chat not found"})
    )
    adapter = _adapter()
    with pytest.raises(TelegramAPIError):
        await adapter.send_text("999", "Hello")
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_me_returns_bot_info():
    respx.get(f"{TELEGRAM_API_BASE}/bot123:ABC/getMe").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "my_bot"}})
    )
    adapter = _adapter()
    info = await adapter.get_me()
    assert info["username"] == "my_bot"
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_me_raises_on_invalid_token():
    respx.get(f"{TELEGRAM_API_BASE}/bot123:ABC/getMe").mock(
        return_value=httpx.Response(200, json={"ok": False, "description": "Unauthorized"})
    )
    adapter = _adapter()
    with pytest.raises(TelegramAPIError):
        await adapter.get_me()
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_set_webhook_sends_correct_params():
    route = respx.post(f"{TELEGRAM_API_BASE}/bot123:ABC/setWebhook").mock(
        return_value=httpx.Response(200, json={"ok": True, "result": True})
    )
    adapter = _adapter()
    await adapter.set_webhook("https://example.com/webhook/abc", secret_token="abc")
    assert route.called
    body = route.calls[0].request.content
    assert b"https://example.com/webhook/abc" in body
    assert b"abc" in body
    await adapter.aclose()

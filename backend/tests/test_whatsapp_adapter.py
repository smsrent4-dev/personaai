import httpx
import pytest
import respx

from app.models.message import MessageType
from app.services.platforms.whatsapp_adapter import GRAPH_API_BASE, WhatsAppAdapter, WhatsAppAPIError

PHONE_NUMBER_ID = "1234567890"
ACCESS_TOKEN = "EAAtest-access-token"
API_PREFIX = f"{GRAPH_API_BASE}/v20.0/{PHONE_NUMBER_ID}"


def _adapter() -> WhatsAppAdapter:
    return WhatsAppAdapter(phone_number_id=PHONE_NUMBER_ID, access_token=ACCESS_TOKEN, graph_api_version="v20.0")


def _entry(message: dict, contacts: list | None = None) -> dict:
    value = {"metadata": {"phone_number_id": PHONE_NUMBER_ID}, "messages": [message]}
    if contacts is not None:
        value["contacts"] = contacts
    return {"entry": [{"changes": [{"value": value}]}]}


# ---------- parsing ----------

def test_parse_text_message():
    adapter = _adapter()
    payload = _entry(
        {"from": "2348012345678", "id": "wamid.1", "type": "text", "text": {"body": "Hi, do you sell mugs?"}},
        contacts=[{"profile": {"name": "Ada"}}],
    )
    incoming = adapter.parse_incoming(payload)
    assert incoming is not None
    assert incoming.message_type == MessageType.TEXT
    assert incoming.text == "Hi, do you sell mugs?"
    assert incoming.external_conversation_id == "2348012345678"
    assert incoming.external_user_id == "2348012345678"
    assert incoming.external_user_name == "Ada"
    assert incoming.external_message_id == "wamid.1"


def test_parse_image_message_with_caption():
    adapter = _adapter()
    payload = _entry({"from": "1", "id": "wamid.2", "type": "image", "image": {"id": "media1", "caption": "in stock?"}})
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.IMAGE
    assert incoming.media_file_id == "media1"
    assert incoming.text == "in stock?"


def test_parse_video_message():
    adapter = _adapter()
    payload = _entry({"from": "1", "id": "wamid.3", "type": "video", "video": {"id": "media2"}})
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.VIDEO
    assert incoming.media_file_id == "media2"


def test_parse_document_message():
    adapter = _adapter()
    payload = _entry(
        {"from": "1", "id": "wamid.4", "type": "document", "document": {"id": "media3", "filename": "invoice.pdf"}}
    )
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.DOCUMENT
    assert incoming.media_file_id == "media3"
    assert incoming.platform_metadata["filename"] == "invoice.pdf"


def test_parse_voice_note_maps_audio_to_voice():
    adapter = _adapter()
    payload = _entry({"from": "1", "id": "wamid.5", "type": "audio", "audio": {"id": "media4", "voice": True}})
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.VOICE
    assert incoming.media_file_id == "media4"


def test_parse_location_message():
    adapter = _adapter()
    payload = _entry(
        {"from": "1", "id": "wamid.6", "type": "location", "location": {"latitude": 6.5, "longitude": 3.4, "name": "Shop"}}
    )
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.LOCATION
    assert incoming.latitude == 6.5
    assert incoming.longitude == 3.4
    assert incoming.platform_metadata["name"] == "Shop"


def test_parse_contact_message():
    adapter = _adapter()
    payload = _entry(
        {
            "from": "1",
            "id": "wamid.7",
            "type": "contacts",
            "contacts": [{"name": {"formatted_name": "Bob"}, "phones": [{"phone": "+1555"}]}],
        }
    )
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.CONTACT
    assert "Bob" in incoming.text
    assert incoming.platform_metadata["contacts"][0]["name"]["formatted_name"] == "Bob"


def test_parse_interactive_button_reply_maps_to_text():
    adapter = _adapter()
    payload = _entry(
        {
            "from": "1",
            "id": "wamid.8",
            "type": "interactive",
            "interactive": {"type": "button_reply", "button_reply": {"id": "btn_yes", "title": "Yes please"}},
        }
    )
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.TEXT
    assert incoming.text == "Yes please"
    assert incoming.platform_metadata["interactive_reply_id"] == "btn_yes"


def test_parse_interactive_list_reply_maps_to_text():
    adapter = _adapter()
    payload = _entry(
        {
            "from": "1",
            "id": "wamid.9",
            "type": "interactive",
            "interactive": {"type": "list_reply", "list_reply": {"id": "opt_2", "title": "Blue Mug"}},
        }
    )
    incoming = adapter.parse_incoming(payload)
    assert incoming.message_type == MessageType.TEXT
    assert incoming.text == "Blue Mug"


def test_parse_status_update_returns_none():
    adapter = _adapter()
    payload = {
        "entry": [
            {
                "changes": [
                    {"value": {"metadata": {"phone_number_id": PHONE_NUMBER_ID}, "statuses": [{"status": "delivered"}]}}
                ]
            }
        ]
    }
    assert adapter.parse_incoming(payload) is None


def test_parse_malformed_payload_returns_none():
    adapter = _adapter()
    assert adapter.parse_incoming({}) is None
    assert adapter.parse_incoming({"entry": []}) is None


# ---------- outgoing ----------

@pytest.mark.asyncio
@respx.mock
async def test_send_text_splits_long_messages():
    route = respx.post(f"{API_PREFIX}/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "wamid.out"}]}))
    adapter = _adapter()
    await adapter.send_text("1", "a" * 9000)
    assert route.call_count == 3
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_text_raises_on_api_error():
    respx.post(f"{API_PREFIX}/messages").mock(return_value=httpx.Response(400, json={"error": {"message": "bad"}}))
    adapter = _adapter()
    with pytest.raises(WhatsAppAPIError):
        await adapter.send_text("1", "hi")
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_photo_routes_through_send_image():
    route = respx.post(f"{API_PREFIX}/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "1"}]}))
    adapter = _adapter()
    await adapter.send_photo("1", "https://example.com/mug.jpg", caption="Our best seller")
    assert route.call_count == 1
    body = respx.calls[0].request.content
    import json as _json

    assert _json.loads(body)["type"] == "image"
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_document_video_audio_location_contact():
    respx.post(f"{API_PREFIX}/messages").mock(return_value=httpx.Response(200, json={"messages": [{"id": "1"}]}))
    adapter = _adapter()
    await adapter.send_document("1", "https://example.com/invoice.pdf", filename="invoice.pdf")
    await adapter.send_video("1", "https://example.com/demo.mp4")
    await adapter.send_audio("1", "https://example.com/note.ogg")
    await adapter.send_location("1", 6.5, 3.4, name="Shop")
    await adapter.send_contact("1", "Support", "+15551234")
    assert respx.calls.call_count == 5
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_mark_read_with_typing_indicator():
    route = respx.post(f"{API_PREFIX}/messages").mock(return_value=httpx.Response(200, json={"success": True}))
    adapter = _adapter()
    await adapter.mark_read("wamid.1", show_typing=True)
    import json as _json

    body = _json.loads(route.calls[0].request.content)
    assert body["status"] == "read"
    assert body["typing_indicator"]["type"] == "text"
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_download_media_two_step_fetch():
    respx.get(f"{GRAPH_API_BASE}/v20.0/media123").mock(
        return_value=httpx.Response(200, json={"url": "https://lookaside.example.com/file", "mime_type": "image/jpeg"})
    )
    respx.get("https://lookaside.example.com/file").mock(return_value=httpx.Response(200, content=b"binarydata"))
    adapter = _adapter()
    content, mime_type = await adapter.download_media("media123")
    assert content == b"binarydata"
    assert mime_type == "image/jpeg"
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_phone_number_info():
    respx.get(f"{API_PREFIX}").mock(
        return_value=httpx.Response(
            200,
            json={
                "verified_name": "Acme Mugs",
                "display_phone_number": "+1 555 0100",
                "quality_rating": "GREEN",
                "messaging_limit_tier": "TIER_1K",
            },
        )
    )
    adapter = _adapter()
    info = await adapter.get_phone_number_info()
    assert info["verified_name"] == "Acme Mugs"
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_phone_number_info_raises_on_error():
    respx.get(f"{API_PREFIX}").mock(return_value=httpx.Response(400, json={"error": {"message": "Invalid token"}}))
    adapter = _adapter()
    with pytest.raises(WhatsAppAPIError):
        await adapter.get_phone_number_info()
    await adapter.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_subscribe_webhook():
    route = respx.post(f"{GRAPH_API_BASE}/v20.0/waba123/subscribed_apps").mock(
        return_value=httpx.Response(200, json={"success": True})
    )
    adapter = _adapter()
    await adapter.subscribe_webhook("waba123")
    assert route.called
    await adapter.aclose()

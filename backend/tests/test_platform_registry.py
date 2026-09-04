import pytest

from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.services.platforms.registry import build_adapter, is_platform_supported
from app.services.platforms.telegram_adapter import TelegramAdapter
from app.services.platforms.whatsapp_adapter import WhatsAppAdapter


def test_telegram_is_supported():
    assert is_platform_supported(Platform.TELEGRAM) is True


def test_whatsapp_is_supported():
    # WhatsApp (Milestone 8) — Platform.WHATSAPP existed in the enum since
    # Milestone 5's forward-looking design; it's now backed by a real adapter.
    assert is_platform_supported(Platform.WHATSAPP) is True


def test_discord_is_not_yet_supported():
    assert is_platform_supported(Platform.DISCORD) is False


def test_build_adapter_returns_telegram_adapter():
    integration = PlatformIntegration(platform=Platform.TELEGRAM)
    integration.set_credentials({"bot_token": "1:abc"})
    adapter = build_adapter(integration)
    assert isinstance(adapter, TelegramAdapter)
    assert adapter.bot_token == "1:abc"


def test_build_adapter_returns_whatsapp_adapter():
    integration = PlatformIntegration(platform=Platform.WHATSAPP)
    integration.set_credentials({"phone_number_id": "123456", "access_token": "EAAtoken"})
    adapter = build_adapter(integration)
    assert isinstance(adapter, WhatsAppAdapter)
    assert adapter.phone_number_id == "123456"
    assert adapter.access_token == "EAAtoken"


def test_build_adapter_raises_for_unsupported_platform():
    integration = PlatformIntegration(platform=Platform.DISCORD)
    integration.set_credentials({})
    with pytest.raises(ValueError):
        build_adapter(integration)

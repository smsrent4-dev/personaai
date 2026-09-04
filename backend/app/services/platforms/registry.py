"""Adapter registry.

Unlike app/services/ai/factory.py (one cached AIProvider instance per
provider name, shared across all users), adapters are per-integration:
each user's Telegram bot has its own token, so we build a fresh
TelegramAdapter per call rather than caching a singleton. Adding
WhatsApp/Discord/etc. later: implement PlatformAdapter, add one line
to _ADAPTER_REGISTRY, add one branch to build_adapter() for whatever
credentials that platform needs.
"""
from app.config import settings
from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.services.platforms.base import PlatformAdapter
from app.services.platforms.telegram_adapter import TelegramAdapter
from app.services.platforms.whatsapp_adapter import WhatsAppAdapter

_ADAPTER_REGISTRY: dict[Platform, type[PlatformAdapter]] = {
    Platform.TELEGRAM: TelegramAdapter,
    Platform.WHATSAPP: WhatsAppAdapter,
    # Platform.DISCORD: DiscordAdapter,        # future
    # Platform.INSTAGRAM: InstagramAdapter,    # future
    # Platform.MESSENGER: MessengerAdapter,    # future
    # Platform.SLACK: SlackAdapter,            # future
    # Platform.WEB_WIDGET: WebWidgetAdapter,   # future
}


def is_platform_supported(platform: Platform) -> bool:
    return platform in _ADAPTER_REGISTRY


def build_adapter(integration: PlatformIntegration) -> PlatformAdapter:
    adapter_class = _ADAPTER_REGISTRY.get(integration.platform)
    if adapter_class is None:
        raise ValueError(f"No adapter implemented for platform '{integration.platform.value}'")

    if integration.platform == Platform.TELEGRAM:
        return TelegramAdapter(bot_token=integration.get_credentials()["bot_token"])

    if integration.platform == Platform.WHATSAPP:
        credentials = integration.get_credentials()
        return WhatsAppAdapter(
            phone_number_id=credentials["phone_number_id"],
            access_token=credentials["access_token"],
            graph_api_version=settings.META_GRAPH_API_VERSION,
        )

    raise ValueError(f"build_adapter() has no credential-wiring branch for '{integration.platform.value}'")

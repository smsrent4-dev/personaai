"""Platform enum, shared across models and the adapter registry.

Kept in its own module (rather than defined inside integration.py or
conversation.py) because both need the same enum and neither should
import the other just to get it.
"""
import enum


class Platform(str, enum.Enum):
    TELEGRAM = "telegram"
    WHATSAPP = "whatsapp"
    DISCORD = "discord"
    INSTAGRAM = "instagram"
    MESSENGER = "messenger"
    SLACK = "slack"
    WEB_WIDGET = "web_widget"
    VOICE = "voice"

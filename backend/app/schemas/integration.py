import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.integration import IntegrationStatus
from app.models.platform_enums import Platform


class TelegramConnectRequest(BaseModel):
    bot_token: str = Field(min_length=10)


class IntegrationResponse(BaseModel):
    id: uuid.UUID
    platform: Platform
    external_bot_id: str | None
    external_bot_username: str | None
    status: IntegrationStatus
    error_message: str | None
    settings: dict
    created_at: datetime

    model_config = {"from_attributes": True}


class WhatsAppManualConnectRequest(BaseModel):
    business_account_id: str = Field(
        min_length=1,
        description="WhatsApp Business Account ID",
    )
    phone_number_id: str = Field(
        min_length=1,
        description="WhatsApp Phone Number ID",
    )
    access_token: str = Field(
        min_length=10,
        description="WhatsApp Cloud API access token",
    )
    verify_token: str = Field(
        min_length=1,
        description="Value Meta will use for webhook verification",
    )
    webhook_secret: str | None = Field(
        default=None,
        description="Optional additional shared secret",
    )


class WhatsAppTestConnectionRequest(BaseModel):
    phone_number_id: str = Field(
        min_length=1,
        description="WhatsApp Phone Number ID",
    )
    access_token: str = Field(
        min_length=10,
        description="WhatsApp Cloud API access token",
    )


class WhatsAppTestConnectionResponse(BaseModel):
    ok: bool
    verified_name: str | None = None
    display_phone_number: str | None = None
    quality_rating: str | None = None
    messaging_limit_tier: str | None = None
    phone_number_id: str | None = None
    error_code: str | None = None
    error: str | None = None


class WhatsAppOAuthConfigResponse(BaseModel):
    app_id: str
    config_id: str
    graph_api_version: str


class WhatsAppOAuthCallbackRequest(BaseModel):
    code: str = Field(min_length=1)
    redirect_uri: str = Field(min_length=1)


class WhatsAppBusinessProfileResponse(BaseModel):
    id: uuid.UUID
    whatsapp_business_account_id: str
    phone_number_id: str
    business_name: str | None
    display_name: str | None
    display_phone_number: str | None
    quality_rating: str | None
    messaging_tier: str | None
    last_synced_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ConnectionHealthResponse(BaseModel):
    healthy: bool
    checked_at: str
    error: str | None = None


class IntegrationSettingsUpdate(BaseModel):
    auto_reply: bool | None = None
    typing_indicator: bool | None = None
    read_receipts: bool | None = None
    human_takeover: bool | None = None
    default_agent_id: str | None = None
    business_hours: dict | None = None
from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.platform_enums import Platform
from app.models.user import User
from app.schemas.integration import (
    ConnectionHealthResponse,
    IntegrationResponse,
    IntegrationSettingsUpdate,
    TelegramConnectRequest,
    WhatsAppBusinessProfileResponse,
    WhatsAppManualConnectRequest,
    WhatsAppOAuthCallbackRequest,
    WhatsAppOAuthConfigResponse,
    WhatsAppTestConnectionRequest,
    WhatsAppTestConnectionResponse,
)
from app.services.integration_service import IntegrationService

router = APIRouter(prefix="/integrations", tags=["Integrations"])


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)
    return await service.list_integrations(current_user.id)


@router.post(
    "/telegram",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_telegram(
    data: TelegramConnectRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.connect_telegram(
        current_user,
        data.bot_token,
    )


@router.delete(
    "/telegram",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_telegram(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    await service.disconnect(
        current_user.id,
        Platform.TELEGRAM,
    )


@router.get(
    "/whatsapp/oauth/config",
    response_model=WhatsAppOAuthConfigResponse,
)
async def whatsapp_oauth_config(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return service.whatsapp_oauth_config()


@router.post(
    "/whatsapp/oauth/callback",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def whatsapp_oauth_callback(
    data: WhatsAppOAuthCallbackRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.connect_whatsapp_oauth(
        owner=current_user,
        code=data.code,
        redirect_uri=data.redirect_uri,
    )


@router.post(
    "/whatsapp/test",
    response_model=WhatsAppTestConnectionResponse,
)
async def test_whatsapp_connection(
    data: WhatsAppTestConnectionRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    info = await service.test_whatsapp_credentials(
        phone_number_id=data.phone_number_id,
        access_token=data.access_token,
    )

    return WhatsAppTestConnectionResponse(
        ok=True,
        verified_name=info.get("verified_name"),
        display_phone_number=info.get("display_phone_number"),
        quality_rating=info.get("quality_rating"),
        messaging_limit_tier=info.get("messaging_limit_tier"),
    )


@router.post(
    "/whatsapp/manual",
    response_model=IntegrationResponse,
    status_code=status.HTTP_201_CREATED,
)
async def connect_whatsapp_manual(
    data: WhatsAppManualConnectRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.connect_whatsapp_manual(
        owner=current_user,
        business_account_id=data.business_account_id,
        phone_number_id=data.phone_number_id,
        access_token=data.access_token,
        verify_token=data.verify_token,
        webhook_secret=data.webhook_secret,
    )


@router.post(
    "/whatsapp/sync",
    response_model=WhatsAppBusinessProfileResponse,
)
async def sync_whatsapp(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.sync_whatsapp_profile(
        current_user.id,
    )


@router.get(
    "/whatsapp/profile",
    response_model=WhatsAppBusinessProfileResponse,
)
async def get_whatsapp_profile(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.get_whatsapp_profile(
        current_user.id,
    )


@router.get(
    "/whatsapp/health",
    response_model=ConnectionHealthResponse,
)
async def whatsapp_health(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.connection_health(
        current_user.id,
        Platform.WHATSAPP,
    )


@router.delete(
    "/whatsapp",
    status_code=status.HTTP_204_NO_CONTENT,
)
async def disconnect_whatsapp(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    await service.disconnect(
        current_user.id,
        Platform.WHATSAPP,
    )


@router.get(
    "/{platform}/settings",
    response_model=IntegrationResponse,
)
async def get_integration_settings(
    platform: Platform,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.get_integration(
        current_user.id,
        platform,
    )


@router.patch(
    "/{platform}/settings",
    response_model=IntegrationResponse,
)
async def update_integration_settings(
    platform: Platform,
    data: IntegrationSettingsUpdate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = IntegrationService(db)

    return await service.update_settings(
        owner_id=current_user.id,
        platform=platform,
        patch=data.model_dump(exclude_none=True),
    )
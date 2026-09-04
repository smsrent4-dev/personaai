import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.plan_limits import enforce_integration_limit
from app.models.integration import (
    IntegrationStatus,
    PlatformIntegration,
    generate_webhook_secret,
)
from app.models.notification import NotificationType
from app.models.platform_enums import Platform
from app.models.user import User
from app.models.whatsapp_profile import WhatsAppBusinessProfile
from app.services.audit_service import AuditService
from app.services.notification_service import NotificationService
from app.services.platforms.meta_oauth import (
    MetaOAuthError,
    discover_business_assets,
    exchange_code_for_token,
)
from app.services.platforms.telegram_adapter import (
    TelegramAPIError,
    TelegramAdapter,
)
from app.services.platforms.whatsapp_adapter import (
    WhatsAppAPIError,
    WhatsAppAdapter,
)


class IntegrationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_integrations(
        self,
        owner_id: uuid.UUID,
    ) -> list[PlatformIntegration]:
        result = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.owner_id == owner_id
            )
        )

        return list(result.scalars().all())

    async def get_integration(
        self,
        owner_id: uuid.UUID,
        platform: Platform,
    ) -> PlatformIntegration:
        result = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.owner_id == owner_id,
                PlatformIntegration.platform == platform,
            )
        )

        integration = result.scalar_one_or_none()

        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Integration not found",
            )

        return integration

    async def get_by_webhook_secret(
        self,
        webhook_secret: str,
    ) -> PlatformIntegration | None:
        result = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.webhook_secret == webhook_secret
            )
        )

        return result.scalar_one_or_none()

    async def connect_telegram(
        self,
        owner: User,
        bot_token: str,
    ) -> PlatformIntegration:
        adapter = TelegramAdapter(
            bot_token=bot_token
        )

        try:
            bot_info = await adapter.get_me()
        except TelegramAPIError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Invalid Telegram bot token: {exc}",
            ) from exc
        finally:
            await adapter.aclose()

        existing = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.owner_id == owner.id,
                PlatformIntegration.platform == Platform.TELEGRAM,
            )
        )

        integration = existing.scalar_one_or_none()

        if integration is None:
            await enforce_integration_limit(
                self.db,
                owner.id,
            )

            integration = PlatformIntegration(
                owner_id=owner.id,
                platform=Platform.TELEGRAM,
                webhook_secret=generate_webhook_secret(),
            )

            self.db.add(integration)

        integration.set_credentials(
            {
                "bot_token": bot_token,
            }
        )

        integration.external_bot_id = (
            str(bot_info.get("id"))
            if bot_info.get("id") is not None
            else None
        )

        integration.external_bot_username = (
            bot_info.get("username")
        )

        integration.status = IntegrationStatus.ACTIVE
        integration.error_message = None

        await self.db.flush()

        webhook_url = (
            f"{settings.API_BASE_URL}"
            f"/api/v1/telegram/webhook/"
            f"{integration.webhook_secret}"
        )

        adapter = TelegramAdapter(
            bot_token=bot_token
        )

        try:
            await adapter.set_webhook(
                webhook_url,
                secret_token=integration.webhook_secret,
            )
        except TelegramAPIError as exc:
            integration.status = IntegrationStatus.ERROR
            integration.error_message = str(exc)[:1000]

            await self.db.commit()

            await NotificationService(self.db).create(
                owner_id=owner.id,
                type_=NotificationType.INTEGRATION_ERROR,
                title="Telegram connection failed",
                body=(
                    "Webhook registration failed: "
                    f"{str(exc)[:200]}"
                ),
                context={
                    "integration_id": str(integration.id)
                },
            )

            await AuditService(self.db).log(
                action="integration.connect_failed",
                user_id=owner.id,
                resource_type="platform_integration",
                resource_id=str(integration.id),
            )

            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Bot token is valid, but registering the Telegram "
                    "webhook failed."
                ),
            ) from exc
        finally:
            await adapter.aclose()

        await self.db.commit()
        await self.db.refresh(integration)

        await AuditService(self.db).log(
            action="integration.connected",
            user_id=owner.id,
            resource_type="platform_integration",
            resource_id=str(integration.id),
        )

        return integration

    async def _get_whatsapp_profile(
        self,
        integration_id: uuid.UUID,
    ) -> WhatsAppBusinessProfile | None:
        result = await self.db.execute(
            select(WhatsAppBusinessProfile).where(
                WhatsAppBusinessProfile.integration_id == integration_id
            )
        )

        return result.scalar_one_or_none()

    async def test_whatsapp_credentials(
        self,
        phone_number_id: str,
        access_token: str,
    ) -> dict:
        if not phone_number_id.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "PHONE_NUMBER_ID_REQUIRED",
                    "message": (
                        "WhatsApp Phone Number ID is required."
                    ),
                },
            )

        if not access_token.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "ACCESS_TOKEN_REQUIRED",
                    "message": (
                        "WhatsApp access token is required."
                    ),
                },
            )

        adapter = WhatsAppAdapter(
            phone_number_id=phone_number_id.strip(),
            access_token=access_token.strip(),
            graph_api_version=settings.META_GRAPH_API_VERSION,
        )

        try:
            token_info = await adapter.validate_access_token()

            phone_info = await adapter.get_phone_number_info(
                phone_number_id.strip()
            )

            phone_info["meta_user_id"] = token_info.get("id")
            phone_info["meta_user_name"] = token_info.get("name")

            return phone_info

        except WhatsAppAPIError as exc:
            detail = {
                "code": (
                    "META_INVALID_ACCESS_TOKEN"
                    if exc.error_code == 190
                    else "META_PHONE_NUMBER_ACCESS_DENIED"
                    if exc.error_code in {10, 100, 200, 294}
                    else "META_WHATSAPP_API_ERROR"
                ),
                "message": str(exc),
            }

            if exc.error_code is not None:
                detail["meta_error_code"] = exc.error_code

            if exc.error_subcode is not None:
                detail["meta_error_subcode"] = exc.error_subcode

            if exc.fbtrace_id:
                detail["fbtrace_id"] = exc.fbtrace_id

            raise HTTPException(
                status_code=(
                    status.HTTP_401_UNAUTHORIZED
                    if exc.error_code == 190
                    else status.HTTP_403_FORBIDDEN
                    if exc.error_code in {10, 200, 294}
                    else status.HTTP_400_BAD_REQUEST
                ),
                detail=detail,
            ) from exc

        finally:
            await adapter.aclose()

    async def connect_whatsapp_manual(
        self,
        owner: User,
        business_account_id: str,
        phone_number_id: str,
        access_token: str,
        verify_token: str,
        webhook_secret: str | None = None,
    ) -> PlatformIntegration:
        adapter = WhatsAppAdapter(
            phone_number_id=phone_number_id.strip(),
            access_token=access_token.strip(),
            graph_api_version=settings.META_GRAPH_API_VERSION,
        )

        try:
            await adapter.validate_access_token()

            phone_info = await adapter.get_phone_number_info(
                phone_number_id.strip()
            )

            await adapter.verify_phone_number_belongs_to_waba(
                business_account_id.strip(),
                phone_number_id.strip(),
            )

            await adapter.get_waba_info(
                business_account_id.strip()
            )

            await adapter.subscribe_webhook(
                business_account_id.strip()
            )

        except WhatsAppAPIError as exc:
            raise _whatsapp_http_exception(
                exc,
                operation="connecting WhatsApp",
            ) from exc
        finally:
            await adapter.aclose()

        return await self._upsert_whatsapp_integration(
            owner=owner,
            business_account_id=business_account_id.strip(),
            phone_number_id=phone_number_id.strip(),
            access_token=access_token.strip(),
            verify_token=verify_token,
            webhook_secret=webhook_secret,
            info=phone_info,
        )

    def whatsapp_oauth_config(self) -> dict:
        return {
            "app_id": settings.META_APP_ID,
            "config_id": settings.META_CONFIG_ID,
            "graph_api_version": settings.META_GRAPH_API_VERSION,
        }

    async def connect_whatsapp_oauth(
        self,
        owner: User,
        code: str,
        redirect_uri: str,
    ) -> PlatformIntegration:
        code = code.strip()
        redirect_uri = redirect_uri.strip()

        if not code:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "META_MISSING_CODE",
                    "message": (
                        "Meta did not provide an authorization code."
                    ),
                },
            )

        if not redirect_uri:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "META_MISSING_REDIRECT_URI",
                    "message": (
                        "The OAuth redirect URI is required."
                    ),
                },
            )

        try:
            access_token = await exchange_code_for_token(
                code=code,
                redirect_uri=redirect_uri,
            )

            assets = await discover_business_assets(
                access_token
            )

        except MetaOAuthError as exc:
            raise _meta_oauth_http_exception(exc) from exc

        phone_number_id = assets.get(
            "phone_number_id"
        )

        waba_id = assets.get(
            "whatsapp_business_account_id"
        )

        if not phone_number_id or not waba_id:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "code": "META_INCOMPLETE_ASSET_RESPONSE",
                    "message": (
                        "Meta completed authentication but did not "
                        "return a usable WhatsApp Business Account "
                        "and phone number."
                    ),
                },
            )

        adapter = WhatsAppAdapter(
            phone_number_id=phone_number_id,
            access_token=access_token,
            graph_api_version=settings.META_GRAPH_API_VERSION,
        )

        try:
            await adapter.validate_access_token()

            phone_info = await adapter.get_phone_number_info(
                phone_number_id
            )

            await adapter.verify_phone_number_belongs_to_waba(
                waba_id,
                phone_number_id,
            )

            await adapter.subscribe_webhook(
                waba_id
            )

        except WhatsAppAPIError as exc:
            raise _whatsapp_http_exception(
                exc,
                operation="completing WhatsApp Embedded Signup",
            ) from exc
        finally:
            await adapter.aclose()

        assets.update(phone_info)

        return await self._upsert_whatsapp_integration(
            owner=owner,
            business_account_id=waba_id,
            phone_number_id=phone_number_id,
            access_token=access_token,
            verify_token="",
            webhook_secret=None,
            info=assets,
        )

    async def _upsert_whatsapp_integration(
        self,
        owner: User,
        business_account_id: str,
        phone_number_id: str,
        access_token: str,
        verify_token: str,
        webhook_secret: str | None,
        info: dict,
    ) -> PlatformIntegration:
        existing = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.owner_id == owner.id,
                PlatformIntegration.platform == Platform.WHATSAPP,
            )
        )

        integration = existing.scalar_one_or_none()

        if integration is None:
            await enforce_integration_limit(
                self.db,
                owner.id,
            )

            integration = PlatformIntegration(
                owner_id=owner.id,
                platform=Platform.WHATSAPP,
                webhook_secret=generate_webhook_secret(),
            )

            self.db.add(integration)

        integration.set_credentials(
            {
                "phone_number_id": phone_number_id,
                "access_token": access_token,
                "verify_token": verify_token,
                "webhook_secret": webhook_secret or "",
            }
        )

        integration.external_bot_id = phone_number_id
        integration.external_bot_username = (
            info.get("display_phone_number")
        )
        integration.status = IntegrationStatus.ACTIVE
        integration.error_message = None

        await self.db.flush()

        profile = await self._get_whatsapp_profile(
            integration.id
        )

        if profile is None:
            profile = WhatsAppBusinessProfile(
                integration_id=integration.id,
                whatsapp_business_account_id=business_account_id,
                phone_number_id=phone_number_id,
            )

            self.db.add(profile)

        profile.whatsapp_business_account_id = business_account_id
        profile.phone_number_id = phone_number_id

        profile.business_name = (
            info.get("verified_name")
            or profile.business_name
        )

        profile.display_name = (
            info.get("verified_name")
            or profile.display_name
        )

        profile.display_phone_number = (
            info.get("display_phone_number")
        )

        profile.quality_rating = (
            info.get("quality_rating")
        )

        profile.messaging_tier = (
            info.get("messaging_limit_tier")
        )

        profile.last_synced_at = datetime.now(
            timezone.utc
        )

        profile.created_by = (
            profile.created_by
            or owner.id
        )

        profile.updated_by = owner.id

        await self.db.commit()
        await self.db.refresh(integration)

        await AuditService(self.db).log(
            action="integration.connected",
            user_id=owner.id,
            resource_type="platform_integration",
            resource_id=str(integration.id),
            context={
                "platform": "whatsapp",
                "waba_id": business_account_id,
                "phone_number_id": phone_number_id,
            },
        )

        return integration

    async def sync_whatsapp_profile(
        self,
        owner_id: uuid.UUID,
    ) -> WhatsAppBusinessProfile:
        integration = await self.get_integration(
            owner_id,
            Platform.WHATSAPP,
        )

        credentials = integration.get_credentials()

        phone_number_id = credentials.get(
            "phone_number_id"
        )

        access_token = credentials.get(
            "access_token"
        )

        if not phone_number_id or not access_token:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "WHATSAPP_CREDENTIALS_INCOMPLETE",
                    "message": (
                        "The stored WhatsApp integration is missing "
                        "its Phone Number ID or access token. "
                        "Reconnect WhatsApp."
                    ),
                },
            )

        adapter = WhatsAppAdapter(
            phone_number_id=phone_number_id,
            access_token=access_token,
            graph_api_version=settings.META_GRAPH_API_VERSION,
        )

        try:
            info = await adapter.get_phone_number_info()

        except WhatsAppAPIError as exc:
            integration.status = IntegrationStatus.ERROR
            integration.error_message = str(exc)[:1000]

            await self.db.commit()

            raise _whatsapp_http_exception(
                exc,
                operation="syncing WhatsApp",
            ) from exc

        finally:
            await adapter.aclose()

        profile = await self._get_whatsapp_profile(
            integration.id
        )

        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="WhatsApp profile not found",
            )

        profile.display_phone_number = (
            info.get("display_phone_number")
        )

        profile.quality_rating = (
            info.get("quality_rating")
        )

        profile.messaging_tier = (
            info.get("messaging_limit_tier")
        )

        profile.business_name = (
            info.get("verified_name")
            or profile.business_name
        )

        profile.last_synced_at = datetime.now(
            timezone.utc
        )

        integration.status = IntegrationStatus.ACTIVE
        integration.error_message = None

        await self.db.commit()
        await self.db.refresh(profile)

        return profile

    async def get_whatsapp_profile(
        self,
        owner_id: uuid.UUID,
    ) -> WhatsAppBusinessProfile:
        integration = await self.get_integration(
            owner_id,
            Platform.WHATSAPP,
        )

        profile = await self._get_whatsapp_profile(
            integration.id
        )

        if profile is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="WhatsApp profile not found",
            )

        return profile

    async def connection_health(
        self,
        owner_id: uuid.UUID,
        platform: Platform,
    ) -> dict:
        integration = await self.get_integration(
            owner_id,
            platform,
        )

        if platform == Platform.WHATSAPP:
            credentials = integration.get_credentials()

            adapter = WhatsAppAdapter(
                phone_number_id=credentials.get(
                    "phone_number_id",
                    "",
                ),
                access_token=credentials.get(
                    "access_token",
                    "",
                ),
                graph_api_version=settings.META_GRAPH_API_VERSION,
            )

            try:
                await adapter.validate_access_token()
                await adapter.get_phone_number_info()

                return {
                    "healthy": True,
                    "checked_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "error": None,
                }

            except WhatsAppAPIError as exc:
                return {
                    "healthy": False,
                    "checked_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "error": str(exc),
                }

            finally:
                await adapter.aclose()

        if platform == Platform.TELEGRAM:
            adapter = TelegramAdapter(
                bot_token=integration.get_credentials().get(
                    "bot_token",
                    "",
                )
            )

            try:
                await adapter.get_me()

                return {
                    "healthy": True,
                    "checked_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "error": None,
                }

            except TelegramAPIError as exc:
                return {
                    "healthy": False,
                    "checked_at": datetime.now(
                        timezone.utc
                    ).isoformat(),
                    "error": str(exc),
                }

            finally:
                await adapter.aclose()

        return {
            "healthy": (
                integration.status
                == IntegrationStatus.ACTIVE
            ),
            "checked_at": datetime.now(
                timezone.utc
            ).isoformat(),
            "error": None,
        }

    async def update_settings(
        self,
        owner_id: uuid.UUID,
        platform: Platform,
        patch: dict,
    ) -> PlatformIntegration:
        integration = await self.get_integration(
            owner_id,
            platform,
        )

        integration.settings = {
            **integration.settings,
            **{
                key: value
                for key, value in patch.items()
                if value is not None
            },
        }

        await self.db.commit()
        await self.db.refresh(integration)

        return integration

    async def disconnect(
        self,
        owner_id: uuid.UUID,
        platform: Platform,
    ) -> None:
        integration = await self.get_integration(
            owner_id,
            platform,
        )

        if platform == Platform.TELEGRAM:
            adapter = TelegramAdapter(
                bot_token=integration.get_credentials().get(
                    "bot_token",
                    "",
                )
            )

            try:
                await adapter.delete_webhook()
            except TelegramAPIError:
                pass
            finally:
                await adapter.aclose()

        integration_id = str(integration.id)

        await self.db.delete(integration)
        await self.db.commit()

        await AuditService(self.db).log(
            action="integration.disconnected",
            user_id=owner_id,
            resource_type="platform_integration",
            resource_id=integration_id,
        )


def _whatsapp_http_exception(
    exc: WhatsAppAPIError,
    *,
    operation: str,
) -> HTTPException:
    if exc.error_code == 190:
        http_status = status.HTTP_401_UNAUTHORIZED
        code = "META_INVALID_ACCESS_TOKEN"

    elif exc.error_code in {10, 200, 294}:
        http_status = status.HTTP_403_FORBIDDEN
        code = "META_PERMISSION_DENIED"

    elif exc.error_code == 100:
        http_status = status.HTTP_400_BAD_REQUEST
        code = "META_RESOURCE_NOT_ACCESSIBLE"

    elif exc.status_code == 429:
        http_status = status.HTTP_429_TOO_MANY_REQUESTS
        code = "META_RATE_LIMITED"

    else:
        http_status = (
            exc.status_code
            if exc.status_code
            and 400 <= exc.status_code < 600
            else status.HTTP_502_BAD_GATEWAY
        )
        code = "META_WHATSAPP_API_ERROR"

    detail = {
        "code": code,
        "message": (
            f"Unable to complete {operation}: "
            f"{str(exc)}"
        ),
    }

    if exc.error_code is not None:
        detail["meta_error_code"] = exc.error_code

    if exc.error_subcode is not None:
        detail["meta_error_subcode"] = exc.error_subcode

    if exc.fbtrace_id:
        detail["fbtrace_id"] = exc.fbtrace_id

    return HTTPException(
        status_code=http_status,
        detail=detail,
    )


def _meta_oauth_http_exception(
    exc: MetaOAuthError,
) -> HTTPException:
    if exc.code == "META_INVALID_ACCESS_TOKEN":
        http_status = status.HTTP_401_UNAUTHORIZED

    elif exc.code == "META_PERMISSION_DENIED":
        http_status = status.HTTP_403_FORBIDDEN

    elif exc.code in {
        "META_NO_BUSINESSES",
        "META_NO_WHATSAPP_ASSET",
    }:
        http_status = status.HTTP_422_UNPROCESSABLE_ENTITY

    elif exc.code in {
        "META_TIMEOUT",
        "META_NETWORK_ERROR",
    }:
        http_status = status.HTTP_502_BAD_GATEWAY

    else:
        http_status = (
            exc.status_code
            if exc.status_code
            and 400 <= exc.status_code < 600
            else status.HTTP_400_BAD_REQUEST
        )

    detail = {
        "code": exc.code or "META_OAUTH_ERROR",
        "message": str(exc),
    }

    if exc.meta_error_code is not None:
        detail["meta_error_code"] = exc.meta_error_code

    if exc.meta_error_subcode is not None:
        detail["meta_error_subcode"] = exc.meta_error_subcode

    if exc.fbtrace_id:
        detail["fbtrace_id"] = exc.fbtrace_id

    return HTTPException(
        status_code=http_status,
        detail=detail,
    )
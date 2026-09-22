"""Telegram webhook receiver."""

import logging

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.integration_service import IntegrationService
from app.worker import dispatch_incoming_message

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/telegram",
    tags=["Telegram Webhook"],
)


@router.post(
    "/webhook/{webhook_secret}",
    status_code=204,
)
async def telegram_webhook(
    webhook_secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    integration = await IntegrationService(
        db
    ).get_by_webhook_secret(webhook_secret)

    if (
        integration is None
        or integration.platform != Platform.TELEGRAM
    ):
        return Response(status_code=204)

    header_secret = request.headers.get(
        "X-Telegram-Bot-Api-Secret-Token"
    )

    if header_secret != integration.webhook_secret:
        logger.warning(
            "Telegram webhook secret_token mismatch "
            "for integration %s",
            integration.id,
        )
        return Response(status_code=204)

    try:
        payload = await request.json()
    except Exception:
        logger.warning(
            "Invalid JSON received from Telegram "
            "for integration %s",
            integration.id,
        )
        return Response(status_code=204)

    owner_result = await db.execute(
        select(User).where(
            User.id == integration.owner_id
        )
    )

    owner = owner_result.scalar_one_or_none()

    if owner is None or not owner.is_active:
        return Response(status_code=204)

    business_connection = payload.get(
        "business_connection"
    )

    if business_connection is not None:
        try:
            await IntegrationService(
                db
            ).save_telegram_business_connection(
                integration=integration,
                business_connection=business_connection,
            )
        except Exception:
            logger.error(
                "Failed to save Telegram Business "
                "connection for integration %s",
                integration.id,
                exc_info=True,
            )

        return Response(status_code=204)

    try:
        await dispatch_incoming_message(
            db,
            owner,
            integration,
            payload,
        )
    except Exception:
        logger.error(
            "Failed to enqueue Telegram message "
            "for integration %s",
            integration.id,
            exc_info=True,
        )

    return Response(status_code=204)
"""Telegram webhook receiver.

Deliberately NOT behind get_current_active_user — Telegram's servers
call this directly, they don't have (and shouldn't have) a PersonaAI
account or JWT. Security instead comes from two layers: the
unguessable webhook_secret in the URL path, and Telegram's own
`X-Telegram-Bot-Api-Secret-Token` header (set via setWebhook's
secret_token param in IntegrationService.connect_telegram), which we
verify matches before processing anything.

The actual message processing (routing, RAG, AI generation, sending
the reply) is handed off to Celery via dispatch_incoming_message() (see
app/worker.py) rather than awaited here in production. This endpoint
only does the cheap part — resolve the integration/owner, verify the
signature — and acks Telegram in milliseconds regardless of how long
the AI round-trip takes. That matters at real concurrency: the old
inline version held one of the app's 30 pooled DB connections for the
entire AI call duration per message, which made ~30 messages processing
at once the practical ceiling before requests started queuing and
timing out. In tests (settings.CELERY_TASK_ALWAYS_EAGER=True) the same
call runs the pipeline inline instead — see dispatch_incoming_message's
own docstring for why — so the try/except below still matters there
too, not just as a Celery-enqueue-failure guard.
"""
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

router = APIRouter(prefix="/telegram", tags=["Telegram Webhook"])


@router.post("/webhook/{webhook_secret}", status_code=204)
async def telegram_webhook(
    webhook_secret: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Response:
    integration = await IntegrationService(db).get_by_webhook_secret(webhook_secret)
    if integration is None or integration.platform != Platform.TELEGRAM:
        # 204 rather than 401/403/404 — don't confirm/deny secret validity to a prober,
        # and Telegram doesn't need (or want) an error response to stop retrying here.
        return Response(status_code=204)

    header_secret = request.headers.get("X-Telegram-Bot-Api-Secret-Token")
    if header_secret != integration.webhook_secret:
        logger.warning("Telegram webhook secret_token mismatch for integration %s", integration.id)
        return Response(status_code=204)

    payload = await request.json()

    owner_result = await db.execute(select(User).where(User.id == integration.owner_id))
    owner = owner_result.scalar_one_or_none()
    if owner is None or not owner.is_active:
        return Response(status_code=204)

    try:
        await dispatch_incoming_message(db, owner, integration, payload)
    except Exception:
        # Broker unreachable, etc. — log it (this is the one failure mode
        # that genuinely means a message goes unanswered) but still ack
        # Telegram; there's nothing useful a retry-storm accomplishes here.
        logger.error("Failed to enqueue Telegram message for integration %s", integration.id, exc_info=True)

    return Response(status_code=204)

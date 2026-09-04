"""WhatsApp Cloud API webhook receiver.

Architecturally different from Telegram's webhook (see
telegram_webhook.py) in one important way: Meta's WhatsApp webhook is
registered ONCE per Meta App in the Meta App Dashboard, not once per
connected business. Every WABA connected to that app — i.e. every
PersonaAI owner who connected WhatsApp — has its events delivered to
this SAME URL. So there's no per-integration secret in the path; instead:

  - GET (webhook verification): Meta calls this once, when the URL is
    first configured in the App Dashboard, with `hub.verify_token`. We
    accept it if it matches EITHER the app-level
    `settings.WHATSAPP_APP_VERIFY_TOKEN` OR any connected integration's
    own verify_token (so the manual-setup flow's "Verify Token" field,
    which the spec explicitly asks for, is actually meaningful even
    though Meta's real design only needs one app-level token).
  - POST (events): authenticity comes from `X-Hub-Signature-256`, an
    HMAC-SHA256 of the raw body keyed by `settings.META_APP_SECRET` —
    this is Meta's actual mechanism, verified with `hmac.compare_digest`
    the same way PaystackService verifies its webhook signature.
    Routing to the correct owner/integration then happens by reading the
    phone_number_id out of the payload itself (`entry[].changes[].
    value.metadata.phone_number_id`) and looking up the matching
    PlatformIntegration — there's no other way to know whose message
    this is, since the URL doesn't tell us.

Once resolved to an (owner, integration) pair, everything downstream is
identical to Telegram: handed off to the same Celery task
(process_incoming_message_task, see app/worker.py and
telegram_webhook.py's docstring for why this is backgrounded rather
than awaited inline). The Router never knows which platform sent the
message.
"""
import hashlib
import hmac
import logging

from fastapi import APIRouter, Depends, Query, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.integration import PlatformIntegration
from app.models.platform_enums import Platform
from app.models.user import User
from app.services.platforms.whatsapp_adapter import WhatsAppAdapter
from app.worker import dispatch_incoming_message

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["WhatsApp Webhook"])


@router.get("/webhook")
async def verify_whatsapp_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    hub_mode: str = Query(alias="hub.mode"),
    hub_verify_token: str = Query(alias="hub.verify_token"),
    hub_challenge: str = Query(alias="hub.challenge"),
):
    if hub_mode != "subscribe":
        return Response(status_code=status.HTTP_403_FORBIDDEN)

    if hub_verify_token == settings.WHATSAPP_APP_VERIFY_TOKEN and settings.WHATSAPP_APP_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")

    # Fall back to checking every connected WhatsApp integration's own
    # verify_token (the manual-setup flow's per-integration field).
    result = await db.execute(select(PlatformIntegration).where(PlatformIntegration.platform == Platform.WHATSAPP))
    for integration in result.scalars().all():
        if integration.get_credentials().get("verify_token") == hub_verify_token:
            return Response(content=hub_challenge, media_type="text/plain")

    logger.warning("WhatsApp webhook verification failed: no matching verify_token")
    return Response(status_code=status.HTTP_403_FORBIDDEN)


@router.post("/webhook", status_code=204)
async def receive_whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Response:
    raw_body = await request.body()

    if not _verify_signature(raw_body, request.headers.get("X-Hub-Signature-256")):
        logger.warning("WhatsApp webhook signature verification failed")
        return Response(status_code=204)  # ack without processing — don't reveal validity to a prober

    payload = await request.json()

    try:
        phone_number_id = payload["entry"][0]["changes"][0]["value"]["metadata"]["phone_number_id"]
    except (KeyError, IndexError, TypeError):
        # Not a message change (e.g. a template status update) — nothing to route.
        return Response(status_code=204)

    integration = await _find_integration_by_phone_number_id(db, phone_number_id)
    if integration is None:
        logger.info("WhatsApp webhook for unknown phone_number_id %s", phone_number_id)
        return Response(status_code=204)

    owner_result = await db.execute(select(User).where(User.id == integration.owner_id))
    owner = owner_result.scalar_one_or_none()
    if owner is None or not owner.is_active:
        return Response(status_code=204)

    try:
        await dispatch_incoming_message(db, owner, integration, payload)
    except Exception:
        logger.error("Failed to enqueue WhatsApp message for integration %s", integration.id, exc_info=True)

    return Response(status_code=204)


def _verify_signature(raw_body: bytes, signature_header: str | None) -> bool:
    if not settings.META_APP_SECRET:
        # No app secret configured (e.g. local dev without Embedded Signup
        # set up) — can't verify, so we can't safely accept either. Fail
        # closed rather than silently trusting unsigned payloads.
        logger.warning("META_APP_SECRET not configured; rejecting WhatsApp webhook")
        return False
    if not signature_header or not signature_header.startswith("sha256="):
        return False
    expected = hmac.new(settings.META_APP_SECRET.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    provided = signature_header.removeprefix("sha256=")
    return hmac.compare_digest(expected, provided)


async def _find_integration_by_phone_number_id(db: AsyncSession, phone_number_id: str) -> PlatformIntegration | None:
    from app.models.whatsapp_profile import WhatsAppBusinessProfile

    result = await db.execute(
        select(PlatformIntegration)
        .join(WhatsAppBusinessProfile, WhatsAppBusinessProfile.integration_id == PlatformIntegration.id)
        .where(WhatsAppBusinessProfile.phone_number_id == phone_number_id)
    )
    return result.scalar_one_or_none()


@router.get("/media/{integration_id}/{media_id}")
async def get_whatsapp_media(
    integration_id: str,
    media_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Streams a WhatsApp media attachment (image/voice/document/video) so
    the Conversation Viewer can render previews/playback/downloads without
    the frontend needing a Graph API access token of its own. Scoped to
    the requesting user's own integration, same tenant-isolation rule as
    every other endpoint in this codebase — a 404, not a 403, if the
    integration belongs to someone else, so its existence isn't confirmed."""
    import uuid

    from fastapi import HTTPException
    from fastapi.responses import Response as FastAPIResponse

    result = await db.execute(select(PlatformIntegration).where(PlatformIntegration.id == uuid.UUID(integration_id)))
    integration = result.scalar_one_or_none()
    if integration is None or integration.platform != Platform.WHATSAPP or integration.owner_id != current_user.id:
        raise HTTPException(status_code=404, detail="Integration not found")

    credentials = integration.get_credentials()
    adapter = WhatsAppAdapter(
        phone_number_id=credentials["phone_number_id"],
        access_token=credentials["access_token"],
        graph_api_version=settings.META_GRAPH_API_VERSION,
    )
    try:
        content, mime_type = await adapter.download_media(media_id)
    finally:
        await adapter.aclose()

    return FastAPIResponse(content=content, media_type=mime_type)

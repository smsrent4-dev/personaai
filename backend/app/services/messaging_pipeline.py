"""Production messaging orchestration pipeline.

Flow:

1. Parse platform webhook payload.
2. Get/create conversation.
3. Store inbound message.
4. Mark message as read / typing where supported.
5. Get/create customer.
6. Apply human takeover and subscription-access rules.
7. Apply auto-reply, business-hours and plan-limit rules.
8. Process image / voice messages.
9. Select the appropriate agent.
10. Retrieve knowledge, memory and product context.
11. Build the conversation prompt without duplicating the current message.
12. Generate the AI response.
13. Store the outgoing message.
14. Send the text response.
15. Send a product image ONLY when the customer explicitly requested one.

Production AI-request rules:

- An already-assigned conversation does NOT call the AI router again.
- A conversation with one active agent does NOT call the AI router.
- AI routing is only used when a conversation has no valid assigned
  agent and multiple active agents are available.
- The selected agent is persisted on the conversation.
- Gemini/provider retries remain inside the AI provider.
- This pipeline does not retry the entire inbound message.
- Tool calling is limited to 2 iterations for normal customer messaging.
- Routing errors and generation errors are logged separately.
- Routing failures fall back to deterministic agent selection.
- Payment receipt images are NOT treated as payment confirmation.
- Platform media results are normalized before AI processing.
- Product-image sending is controlled by application logic.
- Normal product searches NEVER automatically send product images.
- AI automation is blocked unless the owner's subscription is ACTIVE.
- Billing remains accessible even when the subscription is inactive.
- Plan-limit notifications are created directly through the Notification
  model because NotificationService does not expose create_notification().
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan_limits import check_message_limit
from app.core.subscription_access import check_subscription_access
from app.models.agent import Agent, AgentStatus
from app.models.conversation import Conversation
from app.models.integration import PlatformIntegration
from app.models.message import Message, MessageRole, MessageType
from app.models.notification import Notification, NotificationType
from app.models.order import OrderStatus, PaymentStatus
from app.models.product import Product
from app.models.user import User
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from app.services.knowledge import KnowledgeService
from app.services.memory_service import MemoryService
from app.services.order_service import OrderService
from app.services.platforms.registry import build_adapter
from app.services.product_service import ProductService
from app.services.router_service import RouterService
from app.services.tools import (
    ToolContext,
    default_tool_definitions,
    execute_tool,
)

logger = logging.getLogger(__name__)


# ============================================================================
# Production AI limits
# ============================================================================

_MAX_TOOL_ITERATIONS = 2


# ============================================================================
# Order / payment constants
# ============================================================================

_AWAITING_PAYMENT_STATUSES = {
    PaymentStatus.UNPAID,
    PaymentStatus.AWAITING_CONFIRMATION,
}

_CLOSED_ORDER_STATUSES = {
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.DELIVERED,
}


# ============================================================================
# Product image intent
# ============================================================================

_PRODUCT_IMAGE_WORDS = (
    "photo",
    "picture",
    "pic",
    "image",
    "images",
    "photos",
    "pictures",
)

_PRODUCT_IMAGE_INTENT_PATTERNS = (
    r"\b(?:send|show|see|view|get|share)\b"
    r".{0,60}\b(?:photo|picture|pic|image|images|photos|pictures)\b",

    r"\b(?:photo|picture|pic|image|images|photos|pictures)\b"
    r".{0,60}\b(?:send|show|see|view|get|share)\b",

    r"\bcan\s+i\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    r"\bcould\s+i\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    r"\b(?:let|allow)\s+me\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    r"\bi\s+(?:want|would\s+like|d['’]like)\s+to\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    r"\bwhat\s+(?:does|do)\b.{0,70}\blook\s+like\b",

    r"\bcan\s+you\s+show\s+me\b.{0,60}\b"
    r"(?:the|this|that|your|a|an)\b",

    r"\bcould\s+you\s+show\s+me\b.{0,60}\b"
    r"(?:the|this|that|your|a|an)\b",

    r"\bshow\s+me\b.{0,60}\b"
    r"(?:photo|picture|pic|image|images|photos|pictures)\b",

    r"\bshow\s+me\b.{0,60}\b"
    r"(?:what\s+it\s+looks\s+like|what\s+that\s+looks\s+like)\b",
)


def _is_product_image_request(text: str | None) -> bool:
    """Return True only when the customer explicitly requests an image."""

    if not text:
        return False

    normalized = " ".join(
        str(text).strip().lower().split()
    )

    if not normalized:
        return False

    return any(
        re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        )
        for pattern in _PRODUCT_IMAGE_INTENT_PATTERNS
    )


def _normalize_product_search_text(
    text: str | None,
) -> str:
    """Remove image-request wording while preserving product wording."""

    if not text:
        return ""

    cleaned = " ".join(
        str(text).strip().lower().split()
    )

    replacements = (
        r"\bcan\s+you\b",
        r"\bcould\s+you\b",
        r"\bcan\s+i\b",
        r"\bcould\s+i\b",
        r"\bplease\b",
        r"\bkindly\b",
        r"\bsend\s+me\b",
        r"\bsend\b",
        r"\bshow\s+me\b",
        r"\bshow\b",
        r"\bshare\s+with\s+me\b",
        r"\bshare\b",
        r"\blet\s+me\s+see\b",
        r"\ballow\s+me\s+to\s+see\b",
        r"\bi\s+want\s+to\s+see\b",
        r"\bi['’]d\s+like\s+to\s+see\b",
        r"\bi\s+would\s+like\s+to\s+see\b",
        r"\bcan\s+i\s+see\b",
        r"\bcould\s+i\s+see\b",
        r"\bwhat\s+(?:does|do)\b",
        r"\bphoto\s+of\b",
        r"\bpicture\s+of\b",
        r"\bpic\s+of\b",
        r"\bimage\s+of\b",
        r"\bphotos\s+of\b",
        r"\bpictures\s+of\b",
        r"\bimages\s+of\b",
        r"\bphoto\b",
        r"\bpicture\b",
        r"\bpic\b",
        r"\bimages?\b",
        r"\bphotos?\b",
        r"\bpictures?\b",
        r"\bwhat\s+it\s+looks\s+like\b",
        r"\bwhat\s+that\s+looks\s+like\b",
        r"\blook\s+like\b",
    )

    for pattern in replacements:
        cleaned = re.sub(
            pattern,
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )

    return re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()


def _product_has_image(
    product: Product | None,
) -> bool:
    """Return True when a product contains a usable image URL."""

    if product is None:
        return False

    images = product.images or []

    if not isinstance(images, list):
        return False

    return any(
        isinstance(image, str)
        and image.strip()
        for image in images
    )


def _build_product_photo_caption(
    product: Product,
) -> str:
    """Build a concise product image caption."""

    lines = [
        f"{product.name} — {product.price} {product.currency}",
    ]

    variants = product.variants or []

    if isinstance(variants, list):
        variant_names = [
            variant.get("name")
            for variant in variants
            if (
                isinstance(variant, dict)
                and variant.get("name")
            )
        ]

        if variant_names:
            lines.append(
                f"Available: {', '.join(variant_names)}"
            )

    if product.inventory is not None:
        if product.inventory > 0:
            lines.append("In stock")
        else:
            lines.append("Currently out of stock")

    if product.description:
        lines.append(
            str(product.description)[:200]
        )

    return "\n".join(lines)[:1024]


# ============================================================================
# Non-text fallbacks
# ============================================================================

_NON_TEXT_ACKNOWLEDGEMENTS = {
    MessageType.IMAGE: (
        "Thanks for the image — I've received it and will follow up shortly."
    ),
    MessageType.DOCUMENT: (
        "Thanks for the document — I've received it and will follow up "
        "shortly."
    ),
    MessageType.VOICE: (
        "Thanks for the voice message — I've received it and will follow "
        "up shortly."
    ),
    MessageType.LOCATION: (
        "Thanks for sharing your location — noted."
    ),
    MessageType.VIDEO: (
        "Thanks for the video — I've received it and will follow up shortly."
    ),
    MessageType.CONTACT: (
        "Thanks for sharing that contact — noted."
    ),
    MessageType.OTHER: "Got it, thanks!",
}


# ============================================================================
# Business hours
# ============================================================================

_WEEKDAY_KEYS = (
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
)


def _after_hours_reply(
    settings: dict,
) -> str | None:
    """Return an after-hours response when business hours are configured."""

    business_hours = settings.get(
        "business_hours"
    )

    if not isinstance(
        business_hours,
        dict,
    ):
        return None

    if not business_hours.get("enabled"):
        return None

    try:
        import zoneinfo

        timezone_name = str(
            business_hours.get(
                "timezone",
                "UTC",
            )
        )

        timezone = zoneinfo.ZoneInfo(
            timezone_name
        )

        now = datetime.now(timezone)

        today_key = _WEEKDAY_KEYS[
            now.weekday()
        ]

        hours = business_hours.get(
            "hours",
            {},
        )

        if not isinstance(hours, dict):
            return None

        window = hours.get(
            today_key
        )

        if not window or len(window) < 2:
            is_open = False

        else:
            open_time = datetime.strptime(
                str(window[0]),
                "%H:%M",
            ).time()

            close_time = datetime.strptime(
                str(window[1]),
                "%H:%M",
            ).time()

            current_time = now.time()

            if open_time <= close_time:
                is_open = (
                    open_time
                    <= current_time
                    <= close_time
                )
            else:
                is_open = (
                    current_time >= open_time
                    or current_time <= close_time
                )

    except Exception:
        logger.warning(
            "Malformed business_hours settings; ignoring rule",
            exc_info=True,
        )
        return None

    if is_open:
        return None

    message = business_hours.get(
        "message"
    )

    if isinstance(message, str) and message.strip():
        return message.strip()

    return (
        "Thanks for reaching out! We're currently outside business "
        "hours and will reply as soon as we're back."
    )


# ============================================================================
# Media normalization
# ============================================================================

def _normalize_downloaded_media(
    media_result: Any,
    default_mime_type: str,
) -> tuple[bytes, str]:
    """Normalize adapter media into `(bytes, mime_type)`."""

    if media_result is None:
        raise ValueError(
            "Platform returned no media data"
        )

    media_bytes: bytes | None = None
    mime_type: str | None = None

    if isinstance(
        media_result,
        bytes,
    ):
        media_bytes = media_result

    elif isinstance(
        media_result,
        bytearray,
    ):
        media_bytes = bytes(
            media_result
        )

    elif isinstance(
        media_result,
        memoryview,
    ):
        media_bytes = media_result.tobytes()

    elif isinstance(
        media_result,
        (tuple, list),
    ):
        for item in media_result:
            if isinstance(
                item,
                bytes,
            ):
                media_bytes = item

            elif isinstance(
                item,
                bytearray,
            ):
                media_bytes = bytes(item)

            elif isinstance(
                item,
                memoryview,
            ):
                media_bytes = item.tobytes()

            elif isinstance(
                item,
                str,
            ):
                value = item.strip()

                if "/" in value:
                    mime_type = value

    else:
        possible_bytes = getattr(
            media_result,
            "content",
            None,
        )

        if isinstance(
            possible_bytes,
            bytes,
        ):
            media_bytes = possible_bytes

        elif isinstance(
            possible_bytes,
            bytearray,
        ):
            media_bytes = bytes(
                possible_bytes
            )

        elif isinstance(
            possible_bytes,
            memoryview,
        ):
            media_bytes = possible_bytes.tobytes()

        possible_mime = getattr(
            media_result,
            "mime_type",
            None,
        )

        if isinstance(
            possible_mime,
            str,
        ):
            possible_mime = possible_mime.strip()

            if possible_mime:
                mime_type = possible_mime

    if not media_bytes:
        raise ValueError(
            "Platform returned media, but no bytes could be extracted "
            f"from type {type(media_result).__name__}"
        )

    return (
        media_bytes,
        mime_type or default_mime_type,
    )


# ============================================================================
# MessagingPipeline
# ============================================================================

class MessagingPipeline:
    """Production inbound messaging orchestration."""

    def __init__(
        self,
        db: AsyncSession,
    ):
        self.db = db

        self.conversation_service = ConversationService(
            db
        )

        self.router_service = RouterService(
            db
        )

        self.knowledge_service = KnowledgeService(
            db
        )

        self.memory_service = MemoryService(
            db
        )

        self.product_service = ProductService(
            db
        )

        self.customer_service = CustomerService(
            db
        )

        self.order_service = OrderService(
            db
        )

    # ========================================================================
    # Main entry point
    # ========================================================================

    async def handle_incoming(
        self,
        owner: User,
        integration: PlatformIntegration,
        raw_payload: dict,
    ) -> None:
        """Process one incoming platform webhook message."""

        adapter = build_adapter(
            integration
        )

        try:
            # ----------------------------------------------------------------
            # 1. Parse webhook
            # ----------------------------------------------------------------

            incoming = adapter.parse_incoming(
                raw_payload
            )

            if incoming is None:
                logger.debug(
                    "Platform adapter ignored payload for integration %s",
                    integration.id,
                )
                return

            logger.info(
                (
                    "Processing incoming message: "
                    "platform=%s conversation=%s type=%s external_id=%s"
                ),
                integration.platform,
                incoming.external_conversation_id,
                incoming.message_type,
                incoming.external_message_id,
            )

            # ----------------------------------------------------------------
            # 2. Get/create conversation
            # ----------------------------------------------------------------

            conversation = (
                await self.conversation_service.get_or_create_conversation(
                    owner_id=owner.id,
                    platform=integration.platform,
                    external_conversation_id=(
                        incoming.external_conversation_id
                    ),
                    external_user_id=(
                        incoming.external_user_id
                    ),
                    external_user_name=(
                        incoming.external_user_name
                    ),
                )
            )

            # ----------------------------------------------------------------
            # 3. Store inbound message
            # ----------------------------------------------------------------

            inbound_message = (
                await self.conversation_service.add_message(
                    conversation,
                    role=MessageRole.USER,
                    content=incoming.text,
                    message_type=incoming.message_type,
                    external_message_id=(
                        incoming.external_message_id
                    ),
                    media_file_id=(
                        incoming.media_file_id
                    ),
                    latitude=incoming.latitude,
                    longitude=incoming.longitude,
                    platform_metadata=(
                        incoming.platform_metadata
                    ),
                )
            )

            await self.db.commit()

            # ----------------------------------------------------------------
            # 4. Mark read / typing
            # ----------------------------------------------------------------

            if (
                incoming.external_message_id
                and integration.settings.get(
                    "read_receipts",
                    True,
                )
            ):
                try:
                    await adapter.mark_read(
                        incoming.external_message_id,
                        show_typing=integration.settings.get(
                            "typing_indicator",
                            True,
                        ),
                    )
                except Exception:
                    logger.debug(
                        "mark_read failed for message %s",
                        incoming.external_message_id,
                        exc_info=True,
                    )

            # ----------------------------------------------------------------
            # 5. Get/create customer
            # ----------------------------------------------------------------

            customer = None

            if incoming.external_user_id:
                customer = (
                    await self.customer_service.get_or_create_customer(
                        owner_id=owner.id,
                        platform=integration.platform,
                        external_user_id=(
                            incoming.external_user_id
                        ),
                        display_name=(
                            incoming.external_user_name
                        ),
                    )
                )

                await self.db.commit()

            # ----------------------------------------------------------------
            # 6. Human takeover
            # ----------------------------------------------------------------

            if conversation.assigned_to_human:
                logger.info(
                    (
                        "Skipping AI reply because conversation %s "
                        "is assigned to a human"
                    ),
                    conversation.id,
                )
                return

            # ----------------------------------------------------------------
            # 7. Subscription access
            #
            # Webhook messages do not pass through FastAPI dependencies.
            # Therefore require_active_subscription() cannot protect this
            # execution path.
            #
            # This check MUST happen before any AI/Gemini operation,
            # including:
            #
            # - image analysis
            # - payment receipt classification
            # - voice transcription
            # - product retrieval
            # - AI routing
            # - AI generation
            #
            # Billing remains accessible through billing endpoints.
            # ----------------------------------------------------------------

            (
                subscription_allowed,
                subscription,
                _subscription_plan,
            ) = await check_subscription_access(
                self.db,
                owner.id,
            )

            if not subscription_allowed:
                subscription_status = (
                    subscription.status.value
                    if subscription is not None
                    else "none"
                )

                logger.info(
                    (
                        "Skipping AI automation because subscription "
                        "is not active: owner=%s conversation=%s "
                        "status=%s"
                    ),
                    owner.id,
                    conversation.id,
                    subscription_status,
                )

                return

            # ----------------------------------------------------------------
            # 8. Auto-reply setting
            # ----------------------------------------------------------------

            if not integration.settings.get(
                "auto_reply",
                True,
            ):
                logger.info(
                    (
                        "Skipping AI reply because auto_reply is disabled "
                        "for integration %s"
                    ),
                    integration.id,
                )
                return

            # ----------------------------------------------------------------
            # 9. Business hours
            # ----------------------------------------------------------------

            after_hours_reply = _after_hours_reply(
                integration.settings
            )

            if after_hours_reply:
                await self.conversation_service.add_message(
                    conversation,
                    role=MessageRole.SYSTEM,
                    content=after_hours_reply,
                )

                await self.db.commit()

                try:
                    await adapter.send_text(
                        incoming.external_conversation_id,
                        after_hours_reply,
                    )
                except Exception:
                    logger.warning(
                        (
                            "Failed to send after-hours reply "
                            "for conversation %s"
                        ),
                        conversation.id,
                        exc_info=True,
                    )

                return

            # ----------------------------------------------------------------
            # 10. Plan limit
            # ----------------------------------------------------------------

            limit_reached, plan = (
                await check_message_limit(
                    self.db,
                    owner.id,
                )
            )

            if limit_reached:
                await self._handle_message_limit_reached(
                    owner=owner,
                    integration=integration,
                    conversation=conversation,
                    adapter=adapter,
                    plan=plan,
                )
                return

            # ----------------------------------------------------------------
            # 11. Process media
            # ----------------------------------------------------------------

            effective_text = incoming.text

            if (
                incoming.message_type == MessageType.IMAGE
                and incoming.media_file_id
            ):
                handled, effective_text = (
                    await self._handle_image_message(
                        owner=owner,
                        conversation=conversation,
                        customer=customer,
                        incoming=incoming,
                        adapter=adapter,
                        inbound_message=inbound_message,
                    )
                )

                if handled:
                    return

            elif (
                incoming.message_type == MessageType.VOICE
                and incoming.media_file_id
            ):
                effective_text = (
                    await self._transcribe_voice(
                        incoming=incoming,
                        adapter=adapter,
                        inbound_message=inbound_message,
                    )
                )

                if not effective_text:
                    fallback_message = (
                        "I received your voice message, but I couldn't "
                        "understand the audio right now. Please try sending "
                        "the voice note again."
                    )

                    await self.conversation_service.add_message(
                        conversation,
                        role=MessageRole.AGENT,
                        content=fallback_message,
                    )

                    await self.db.commit()

                    try:
                        await adapter.send_text(
                            incoming.external_conversation_id,
                            fallback_message,
                        )
                    except Exception:
                        logger.warning(
                            (
                                "Failed to send voice fallback "
                                "for conversation %s"
                            ),
                            conversation.id,
                            exc_info=True,
                        )

                    return

            # ----------------------------------------------------------------
            # 12. Detect explicit product image request
            # ----------------------------------------------------------------

            wants_product_image = (
                _is_product_image_request(
                    effective_text
                )
            )

            if wants_product_image:
                logger.info(
                    (
                        "Explicit product image request detected: "
                        "conversation=%s text=%s"
                    ),
                    conversation.id,
                    effective_text,
                )

            # ----------------------------------------------------------------
            # 13. Select agent
            # ----------------------------------------------------------------

            agent = None

            try:
                agent = await self._select_agent(
                    owner_id=owner.id,
                    conversation=conversation,
                    integration=integration,
                    message=effective_text,
                )

                if agent is not None:
                    logger.info(
                        (
                            "Agent selected: "
                            "conversation=%s agent=%s"
                        ),
                        conversation.id,
                        agent.id,
                    )

            except Exception:
                logger.error(
                    (
                        "Agent selection failed for conversation %s; "
                        "using deterministic fallback"
                    ),
                    conversation.id,
                    exc_info=True,
                )

                try:
                    agent = (
                        await self._pick_agent_without_ai(
                            owner.id,
                            conversation,
                            integration,
                        )
                    )

                except Exception:
                    logger.error(
                        (
                            "Deterministic agent selection failed "
                            "for conversation %s"
                        ),
                        conversation.id,
                        exc_info=True,
                    )

                    agent = None

            # ----------------------------------------------------------------
            # 14. Generate AI response
            # ----------------------------------------------------------------

            if agent is None:
                reply_text = (
                    "Sorry, we're unable to respond right now. "
                    "A team member will follow up shortly."
                )

                requested_product = None

            else:
                try:
                    logger.info(
                        (
                            "Generating AI reply: "
                            "conversation=%s agent=%s type=%s"
                        ),
                        conversation.id,
                        agent.id,
                        incoming.message_type,
                    )

                    (
                        reply_text,
                        _top_product,
                        requested_product,
                    ) = await self._build_reply(
                        owner=owner,
                        conversation=conversation,
                        incoming=incoming,
                        inbound_message=inbound_message,
                        agent=agent,
                        customer=customer,
                        effective_text=effective_text,
                        wants_product_image=wants_product_image,
                    )

                    reply_text = str(
                        reply_text or ""
                    ).strip()

                    if not reply_text:
                        raise ValueError(
                            "AI provider returned an empty reply"
                        )

                    logger.info(
                        (
                            "AI reply generated successfully "
                            "for conversation %s"
                        ),
                        conversation.id,
                    )

                except Exception:
                    logger.error(
                        (
                            "AI reply generation failed for "
                            "conversation %s using agent %s"
                        ),
                        conversation.id,
                        agent.id,
                        exc_info=True,
                    )

                    reply_text = (
                        "Sorry, something went wrong on our end. "
                        "We'll follow up shortly."
                    )

                    requested_product = None

            # ----------------------------------------------------------------
            # 15. Store outgoing message
            # ----------------------------------------------------------------

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=reply_text,
                agent_id=(
                    agent.id
                    if agent is not None
                    else None
                ),
            )

            await self.db.commit()

            # ----------------------------------------------------------------
            # 16. Send text
            # ----------------------------------------------------------------

            try:
                await adapter.send_text(
                    incoming.external_conversation_id,
                    reply_text,
                )
            except Exception:
                logger.error(
                    (
                        "Failed to send AI text response "
                        "for conversation %s"
                    ),
                    conversation.id,
                    exc_info=True,
                )

                # Do not retry the entire inbound pipeline.
                return

            # ----------------------------------------------------------------
            # 17. Send product image ONLY when explicitly requested
            # ----------------------------------------------------------------

            if (
                wants_product_image
                and requested_product is not None
                and _product_has_image(
                    requested_product
                )
            ):
                try:
                    image_url = str(
                        requested_product.images[0]
                    ).strip()

                    caption = (
                        _build_product_photo_caption(
                            requested_product
                        )
                    )

                    logger.info(
                        (
                            "Sending requested product image: "
                            "conversation=%s product=%s"
                        ),
                        conversation.id,
                        requested_product.id,
                    )

                    await adapter.send_photo(
                        incoming.external_conversation_id,
                        image_url,
                        caption,
                    )

                    logger.info(
                        (
                            "Requested product image sent successfully: "
                            "conversation=%s product=%s"
                        ),
                        conversation.id,
                        requested_product.id,
                    )

                except Exception:
                    logger.warning(
                        (
                            "Failed to send requested product image "
                            "for product %s"
                        ),
                        requested_product.id,
                        exc_info=True,
                    )

            elif wants_product_image:
                logger.info(
                    (
                        "Customer explicitly requested a product image, "
                        "but no matching product image was available: "
                        "conversation=%s"
                    ),
                    conversation.id,
                )

            logger.info(
                (
                    "Incoming message processing completed: "
                    "conversation=%s"
                ),
                conversation.id,
            )

        except Exception:
            logger.error(
                (
                    "Unhandled messaging pipeline error "
                    "for integration %s"
                ),
                integration.id,
                exc_info=True,
            )

            raise

        finally:
            aclose = getattr(
                adapter,
                "aclose",
                None,
            )

            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    logger.debug(
                        "Platform adapter close failed",
                        exc_info=True,
                    )

    # ========================================================================
    # Agent selection
    # ========================================================================

    async def _select_agent(
        self,
        owner_id,
        conversation: Conversation,
        integration: PlatformIntegration,
        message: str | None,
    ) -> Agent:
        """Select an agent while minimizing unnecessary AI routing."""

        # --------------------------------------------------------------------
        # 1. Reuse existing active conversation assignment.
        # --------------------------------------------------------------------

        if conversation.agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == conversation.agent_id,
                    Agent.owner_id == owner_id,
                    Agent.status == AgentStatus.ACTIVE,
                )
            )

            assigned_agent = result.scalar_one_or_none()

            if assigned_agent is not None:
                logger.info(
                    (
                        "Reusing existing conversation agent; "
                        "AI routing skipped: conversation=%s agent=%s"
                    ),
                    conversation.id,
                    assigned_agent.id,
                )

                return assigned_agent

            logger.warning(
                (
                    "Conversation %s has an invalid/inactive agent "
                    "assignment; selecting a new active agent"
                ),
                conversation.id,
            )

        # --------------------------------------------------------------------
        # 2. Load active agents.
        # --------------------------------------------------------------------

        result = await self.db.execute(
            select(Agent)
            .where(
                Agent.owner_id == owner_id,
                Agent.status == AgentStatus.ACTIVE,
            )
            .order_by(
                Agent.created_at.asc()
            )
        )

        active_agents = list(
            result.scalars().all()
        )

        if not active_agents:
            raise RuntimeError(
                "No active AI agent is available for this account."
            )

        # --------------------------------------------------------------------
        # 3. Only one active agent -> no Gemini routing.
        # --------------------------------------------------------------------

        if len(active_agents) == 1:
            agent = active_agents[0]

            logger.info(
                (
                    "Only one active agent exists; "
                    "AI routing skipped: conversation=%s agent=%s"
                ),
                conversation.id,
                agent.id,
            )

            await self._persist_agent_assignment(
                conversation,
                agent,
            )

            return agent

        # --------------------------------------------------------------------
        # 4. Multiple active agents + no message -> deterministic fallback.
        # --------------------------------------------------------------------

        if not message:
            logger.info(
                (
                    "No text available for AI routing; "
                    "using deterministic agent selection: "
                    "conversation=%s"
                ),
                conversation.id,
            )

            agent = await self._pick_agent_without_ai(
                owner_id,
                conversation,
                integration,
            )

            await self._persist_agent_assignment(
                conversation,
                agent,
            )

            return agent

        # --------------------------------------------------------------------
        # 5. Multiple active agents + no assignment -> AI route.
        # --------------------------------------------------------------------

        logger.info(
            (
                "No assigned agent and multiple active agents exist; "
                "calling AI router: conversation=%s active_agents=%s"
            ),
            conversation.id,
            len(active_agents),
        )

        agent = await self.router_service.route(
            owner_id,
            message,
        )

        if agent is None:
            raise RuntimeError(
                "AI router returned no agent."
            )

        if agent.owner_id != owner_id:
            raise RuntimeError(
                "AI router returned an agent belonging to another owner."
            )

        if agent.status != AgentStatus.ACTIVE:
            raise RuntimeError(
                "AI router selected an inactive agent."
            )

        await self._persist_agent_assignment(
            conversation,
            agent,
        )

        logger.info(
            (
                "AI routing completed and assignment persisted: "
                "conversation=%s agent=%s"
            ),
            conversation.id,
            agent.id,
        )

        return agent

    async def _persist_agent_assignment(
        self,
        conversation: Conversation,
        agent: Agent,
    ) -> None:
        """Persist the selected agent on the conversation."""

        if conversation.agent_id == agent.id:
            return

        try:
            conversation.agent_id = agent.id

            await self.db.commit()

        except Exception:
            await self.db.rollback()

            logger.warning(
                (
                    "Could not persist agent assignment for "
                    "conversation %s"
                ),
                conversation.id,
                exc_info=True,
            )

    # ========================================================================
    # Plan limit
    # ========================================================================

    async def _handle_message_limit_reached(
        self,
        owner: User,
        integration: PlatformIntegration,
        conversation: Conversation,
        adapter: Any,
        plan: Any,
    ) -> None:
        """Send plan-limit response and notify the owner once per 24 hours."""

        reply = (
            "Thanks for your message! We've reached our messaging limit "
            "for this month — a team member will get back to you as soon "
            "as possible."
        )

        # --------------------------------------------------------------------
        # Store customer-facing plan-limit response.
        # --------------------------------------------------------------------

        await self.conversation_service.add_message(
            conversation,
            role=MessageRole.SYSTEM,
            content=reply,
        )

        await self.db.commit()

        # --------------------------------------------------------------------
        # Send customer-facing plan-limit response.
        # --------------------------------------------------------------------

        try:
            await adapter.send_text(
                conversation.external_conversation_id,
                reply,
            )
        except Exception:
            logger.warning(
                (
                    "Failed to send plan-limit message "
                    "for conversation %s"
                ),
                conversation.id,
                exc_info=True,
            )

        # --------------------------------------------------------------------
        # Create owner notification once every 24 hours.
        #
        # IMPORTANT:
        # NotificationService currently does not expose
        # create_notification(), so we create the model directly.
        # --------------------------------------------------------------------

        try:
            since = (
                datetime.now().astimezone()
                - timedelta(hours=24)
            )

            result = await self.db.execute(
                select(Notification)
                .where(
                    Notification.owner_id == owner.id,
                    Notification.type
                    == NotificationType.PLAN_LIMIT_REACHED,
                    Notification.created_at >= since,
                )
                .order_by(
                    Notification.created_at.desc()
                )
            )

            existing_notification = (
                result.scalars().first()
            )

            if existing_notification is not None:
                logger.debug(
                    (
                        "Plan-limit notification already exists "
                        "within the last 24 hours: owner=%s"
                    ),
                    owner.id,
                )
                return

            notification = Notification(
                owner_id=owner.id,
                type=NotificationType.PLAN_LIMIT_REACHED,
                title="Monthly messaging limit reached",
                message=(
                    "Your monthly messaging limit has been reached. "
                    "Customers can still be handled manually."
                ),
            )

            self.db.add(
                notification
            )

            await self.db.commit()

            logger.info(
                (
                    "Plan-limit notification created: "
                    "owner=%s notification=%s"
                ),
                owner.id,
                notification.id,
            )

        except Exception:
            await self.db.rollback()

            logger.warning(
                (
                    "Failed to create plan-limit notification "
                    "for owner %s"
                ),
                owner.id,
                exc_info=True,
            )

    # ========================================================================
    # Receipt order lookup
    # ========================================================================

    async def _find_receipt_target_order(
        self,
        owner_id,
        customer_id,
    ):
        """Find the newest customer order awaiting payment."""

        orders = await self.order_service.list_orders(
            owner_id,
            customer_id=customer_id,
        )

        for order in orders:
            if order.status in _CLOSED_ORDER_STATUSES:
                continue

            if order.payment_status in _AWAITING_PAYMENT_STATUSES:
                return order

        return None

    # ========================================================================
    # MIME helpers
    # ========================================================================

    @staticmethod
    def _get_media_mime_type(
        incoming,
        default: str,
    ) -> str:
        """Read MIME type from incoming platform metadata."""

        metadata = getattr(
            incoming,
            "platform_metadata",
            None,
        )

        if not isinstance(
            metadata,
            dict,
        ):
            metadata = {}

        mime_type = (
            metadata.get("mime_type")
            or metadata.get("mimeType")
            or metadata.get("content_type")
            or metadata.get("contentType")
        )

        if isinstance(
            mime_type,
            str,
        ):
            mime_type = mime_type.strip().lower()

            if mime_type:
                return mime_type

        return default

    # ========================================================================
    # Image processing
    # ========================================================================

    async def _handle_image_message(
        self,
        owner: User,
        conversation: Conversation,
        customer,
        incoming,
        adapter,
        inbound_message: Message,
    ) -> tuple[bool, str | None]:
        """Download and analyze an incoming image."""

        if not incoming.media_file_id:
            return (
                False,
                incoming.text,
            )

        try:
            logger.info(
                "Downloading image for conversation %s",
                conversation.id,
            )

            media_result = (
                await adapter.download_media(
                    incoming.media_file_id
                )
            )

            image_data, mime_type = (
                _normalize_downloaded_media(
                    media_result,
                    default_mime_type=(
                        self._get_media_mime_type(
                            incoming,
                            "image/jpeg",
                        )
                    ),
                )
            )

            logger.info(
                (
                    "Analyzing image for conversation %s "
                    "mime_type=%s"
                ),
                conversation.id,
                mime_type,
            )

            description = (
                await self.router_service.ai_provider.describe_image(
                    image_data,
                    mime_type=mime_type,
                )
            )

            description = str(
                description or ""
            ).strip()

            if not description:
                raise ValueError(
                    "Image analysis returned an empty description"
                )

            effective_text = (
                "[Customer sent a photo.]"
            )

            if incoming.text:
                effective_text += (
                    f"\nCustomer caption: {incoming.text}"
                )

            effective_text += (
                f"\nWhat the photo shows: {description}"
            )

            inbound_message.content = (
                effective_text
            )

            await self.db.commit()

            # ----------------------------------------------------------------
            # Payment receipt classification.
            #
            # Classification NEVER confirms payment.
            # ----------------------------------------------------------------

            if customer is not None:
                is_payment_receipt = False

                try:
                    classification = (
                        await self.router_service.ai_provider.classify(
                            description,
                            labels=[
                                (
                                    "payment_receipt_or_bank_transfer_"
                                    "confirmation"
                                ),
                                "something_else",
                            ],
                        )
                    )

                    normalized = (
                        str(classification)
                        .strip()
                        .lower()
                        .replace(" ", "_")
                        .replace("-", "_")
                    )

                    is_payment_receipt = (
                        "payment_receipt"
                        in normalized
                        or "bank_transfer"
                        in normalized
                        or normalized
                        == (
                            "payment_receipt_or_bank_transfer_"
                            "confirmation"
                        )
                    )

                except Exception:
                    logger.warning(
                        (
                            "Image classification failed for "
                            "conversation %s; treating image normally"
                        ),
                        conversation.id,
                        exc_info=True,
                    )

                if is_payment_receipt:
                    order = (
                        await self._find_receipt_target_order(
                            owner.id,
                            customer.id,
                        )
                    )

                    if order is not None:
                        try:
                            await self.order_service.attach_receipt(
                                order.id,
                                incoming.media_file_id,
                            )

                            confirmation = (
                                "Thanks — I've received the payment "
                                "receipt and attached it to your order. "
                                "We'll verify the payment and confirm it "
                                "shortly."
                            )

                            await self.conversation_service.add_message(
                                conversation,
                                role=MessageRole.AGENT,
                                content=confirmation,
                            )

                            await self.db.commit()

                            try:
                                await adapter.send_text(
                                    incoming.external_conversation_id,
                                    confirmation,
                                )
                            except Exception:
                                logger.warning(
                                    (
                                        "Failed to send payment receipt "
                                        "confirmation for conversation %s"
                                    ),
                                    conversation.id,
                                    exc_info=True,
                                )

                            logger.info(
                                (
                                    "Payment receipt attached to "
                                    "order %s for conversation %s"
                                ),
                                order.id,
                                conversation.id,
                            )

                            return (
                                True,
                                effective_text,
                            )

                        except Exception:
                            logger.error(
                                (
                                    "Failed to attach payment receipt "
                                    "for order %s"
                                ),
                                order.id,
                                exc_info=True,
                            )

            return (
                False,
                effective_text,
            )

        except Exception:
            logger.error(
                (
                    "Image processing failed for conversation %s"
                ),
                conversation.id,
                exc_info=True,
            )

            fallback = _NON_TEXT_ACKNOWLEDGEMENTS.get(
                MessageType.IMAGE,
                "Thanks for the image — I've received it.",
            )

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=fallback,
            )

            await self.db.commit()

            try:
                await adapter.send_text(
                    incoming.external_conversation_id,
                    fallback,
                )
            except Exception:
                logger.warning(
                    "Failed to send image fallback",
                    exc_info=True,
                )

            return (
                True,
                None,
            )

    # ========================================================================
    # Voice processing
    # ========================================================================

    async def _transcribe_voice(
        self,
        incoming,
        adapter,
        inbound_message: Message,
    ) -> str | None:
        """Download and transcribe an incoming voice message."""

        if not incoming.media_file_id:
            return incoming.text

        try:
            logger.info(
                "Downloading voice message %s",
                incoming.media_file_id,
            )

            media_result = (
                await adapter.download_media(
                    incoming.media_file_id
                )
            )

            audio_data, mime_type = (
                _normalize_downloaded_media(
                    media_result,
                    default_mime_type=(
                        self._get_media_mime_type(
                            incoming,
                            "audio/ogg",
                        )
                    ),
                )
            )

            logger.info(
                "Transcribing voice message mime_type=%s",
                mime_type,
            )

            transcript = (
                await self.router_service.ai_provider.transcribe_audio(
                    audio_data,
                    mime_type=mime_type,
                )
            )

            transcript = str(
                transcript or ""
            ).strip()

            if not transcript:
                raise ValueError(
                    "Audio transcription returned empty text"
                )

            inbound_message.content = transcript

            await self.db.commit()

            logger.info(
                "Voice transcription completed successfully"
            )

            return transcript

        except Exception:
            logger.error(
                "Voice transcription failed",
                exc_info=True,
            )

            fallback = (
                str(incoming.text).strip()
                if incoming.text
                else ""
            )

            return fallback or None

    # ========================================================================
    # Deterministic agent selection
    # ========================================================================

    async def _pick_agent_without_ai(
        self,
        owner_id,
        conversation: Conversation,
        integration: PlatformIntegration,
    ) -> Agent:
        """Select an active agent without calling Gemini."""

        # --------------------------------------------------------------------
        # 1. Existing active conversation agent
        # --------------------------------------------------------------------

        if conversation.agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == conversation.agent_id,
                    Agent.owner_id == owner_id,
                    Agent.status == AgentStatus.ACTIVE,
                )
            )

            agent = result.scalar_one_or_none()

            if agent is not None:
                return agent

        # --------------------------------------------------------------------
        # 2. Integration default agent
        # --------------------------------------------------------------------

        default_agent_id = (
            integration.default_agent_id
        )

        if default_agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == default_agent_id,
                    Agent.owner_id == owner_id,
                    Agent.status == AgentStatus.ACTIVE,
                )
            )

            agent = result.scalar_one_or_none()

            if agent is not None:
                return agent

        # --------------------------------------------------------------------
        # 3. First active owner agent
        # --------------------------------------------------------------------

        result = await self.db.execute(
            select(Agent)
            .where(
                Agent.owner_id == owner_id,
                Agent.status == AgentStatus.ACTIVE,
            )
            .order_by(
                Agent.created_at.asc()
            )
        )

        agent = result.scalars().first()

        if agent is not None:
            return agent

        raise RuntimeError(
            "No active AI agent is available for this account."
        )

    # ========================================================================
    # Product matching
    # ========================================================================

    async def _find_requested_product(
        self,
        owner_id,
        query: str | None,
    ) -> Product | None:
        """Find the product explicitly requested by the customer."""

        if not query:
            return None

        original = str(
            query
        ).strip()

        if not original:
            return None

        cleaned = (
            _normalize_product_search_text(
                original
            )
        )

        search_queries: list[str] = []

        if cleaned:
            search_queries.append(
                cleaned
            )

        if (
            original
            and original.lower() != cleaned.lower()
        ):
            search_queries.append(
                original
            )

        best_product: Product | None = None
        best_score = float("-inf")

        for search_query in search_queries:
            try:
                results = (
                    await self.product_service.search(
                        owner_id,
                        search_query,
                        top_k=5,
                    )
                )

            except Exception:
                logger.warning(
                    (
                        "Product search failed while matching "
                        "requested product: query=%s"
                    ),
                    search_query,
                    exc_info=True,
                )
                continue

            if not results:
                continue

            local_product = None
            local_score = float("-inf")

            for product, score in results:
                if product is None:
                    continue

                numeric_score = float(
                    score or 0
                )

                if numeric_score > local_score:
                    local_product = product
                    local_score = numeric_score

            if local_product is not None:
                best_product = local_product
                best_score = local_score

                if search_query == cleaned:
                    break

        if best_product is not None:
            logger.info(
                (
                    "Requested product matched: "
                    "product=%s score=%s query=%s has_image=%s"
                ),
                best_product.id,
                best_score,
                query,
                _product_has_image(best_product),
            )

        return best_product

    # ========================================================================
    # Build AI reply
    # ========================================================================

    async def _build_reply(
        self,
        owner: User,
        conversation: Conversation,
        incoming,
        inbound_message: Message,
        agent: Agent,
        customer,
        effective_text: str | None,
        wants_product_image: bool = False,
    ) -> tuple[
        str,
        Product | None,
        Product | None,
    ]:
        """Build context and generate the AI response."""

        if not effective_text:
            return (
                _NON_TEXT_ACKNOWLEDGEMENTS.get(
                    incoming.message_type,
                    "Got it, thanks!",
                ),
                None,
                None,
            )

        # --------------------------------------------------------------------
        # Knowledge retrieval
        # --------------------------------------------------------------------

        knowledge_results = (
            await self.knowledge_service.search(
                owner.id,
                effective_text,
                agent_id=agent.id,
                top_k=3,
            )
        )

        # --------------------------------------------------------------------
        # Memory retrieval
        # --------------------------------------------------------------------

        memory_results = (
            await self.memory_service.search(
                owner.id,
                effective_text,
                agent_id=agent.id,
                top_k=3,
            )
        )

        # --------------------------------------------------------------------
        # Product retrieval
        # --------------------------------------------------------------------

        product_results = (
            await self.product_service.search(
                owner.id,
                effective_text,
                top_k=3,
            )
        )

        # --------------------------------------------------------------------
        # Explicit image request
        # --------------------------------------------------------------------

        requested_product = None

        if wants_product_image:
            requested_product = (
                await self._find_requested_product(
                    owner.id,
                    effective_text,
                )
            )

        # --------------------------------------------------------------------
        # Conversation history
        # --------------------------------------------------------------------

        history = (
            await self.conversation_service.get_recent_messages(
                conversation.id,
                limit=11,
            )
        )

        # --------------------------------------------------------------------
        # System instruction
        # --------------------------------------------------------------------

        system_instruction = (
            self._build_system_instruction(
                agent=agent,
                knowledge_results=knowledge_results,
                memory_results=memory_results,
                product_results=product_results,
            )
        )

        messaging_capability_instruction = """
Messaging capabilities:

- You operate inside a customer messaging platform.
- The application can send product images separately from your text reply.
- Do not claim that you cannot send images.
- Do not invent image URLs.
- Do not claim an image was delivered unless the application actually sent it.
- For normal product questions, answer normally.
- Do not promise an image unless the customer explicitly requested one.
""".strip()

        system_instruction = (
            f"{system_instruction}\n\n"
            f"{messaging_capability_instruction}"
        ).strip()

        # --------------------------------------------------------------------
        # Explicit image request context
        # --------------------------------------------------------------------

        if requested_product is not None:
            system_instruction = (
                f"{system_instruction}\n\n"
                "PRODUCT IMAGE REQUEST:\n"
                "The customer explicitly requested to see a product image. "
                "The application will attempt to send the matching product "
                "image separately after the text response. Respond naturally "
                "and briefly. Do not claim that the image has already been "
                "delivered.\n"
                f"Requested product: {requested_product.name}"
            )

        # --------------------------------------------------------------------
        # Build conversation prompt
        # --------------------------------------------------------------------

        prompt = self._build_prompt(
            history=history,
            latest_text=effective_text,
            current_message_id=inbound_message.id,
        )

        # --------------------------------------------------------------------
        # Generate with tools when customer exists.
        # --------------------------------------------------------------------

        if customer is not None:
            context = ToolContext(
                db=self.db,
                owner_id=owner.id,
                customer=customer,
                conversation_id=conversation.id,
            )

            async def tool_executor(
                tool_name: str,
                arguments: dict,
            ) -> dict:
                return await execute_tool(
                    tool_name,
                    arguments,
                    context,
                )

            logger.info(
                (
                    "Starting tool-enabled AI generation: "
                    "conversation=%s agent=%s max_tool_iterations=%s"
                ),
                conversation.id,
                agent.id,
                _MAX_TOOL_ITERATIONS,
            )

            reply_text = (
                await self.router_service.ai_provider.generate_with_tools(
                    prompt,
                    tools=default_tool_definitions(),
                    tool_executor=tool_executor,
                    system_instruction=system_instruction,
                    temperature=agent.temperature,
                    max_tool_iterations=_MAX_TOOL_ITERATIONS,
                )
            )

        else:
            logger.info(
                (
                    "Starting standard AI generation: "
                    "conversation=%s agent=%s"
                ),
                conversation.id,
                agent.id,
            )

            reply_text = (
                await self.router_service.ai_provider.generate(
                    prompt,
                    system_instruction=system_instruction,
                    temperature=agent.temperature,
                )
            )

        reply_text = str(
            reply_text or ""
        ).strip()

        if not reply_text:
            raise ValueError(
                "AI provider returned an empty response"
            )

        # --------------------------------------------------------------------
        # Determine semantic product context.
        #
        # This does NOT trigger image delivery.
        # --------------------------------------------------------------------

        top_product = None

        if product_results:
            best_product, _score = product_results[0]

            if best_product is not None:
                top_product = best_product

        if requested_product is not None:
            top_product = requested_product

        return (
            reply_text,
            top_product,
            requested_product,
        )

    # ========================================================================
    # System instruction
    # ========================================================================

    @staticmethod
    def _build_system_instruction(
        agent,
        knowledge_results,
        memory_results,
        product_results,
    ) -> str:
        """Build the AI system instruction."""

        parts: list[str] = []

        if agent.instructions:
            parts.append(
                str(agent.instructions).strip()
            )

        # --------------------------------------------------------------------
        # Knowledge
        # --------------------------------------------------------------------

        if knowledge_results:
            knowledge_lines = "\n".join(
                f"- {chunk.content}"
                for chunk, _score in knowledge_results
                if chunk.content
            )

            if knowledge_lines:
                parts.append(
                    "Relevant knowledge base entries:\n"
                    f"{knowledge_lines}"
                )

        # --------------------------------------------------------------------
        # Memory
        # --------------------------------------------------------------------

        if memory_results:
            memory_lines = "\n".join(
                f"- {entry.content}"
                for entry, _score in memory_results
                if entry.content
            )

            if memory_lines:
                parts.append(
                    "Relevant things you know/remember:\n"
                    f"{memory_lines}"
                )

        # --------------------------------------------------------------------
        # Products
        # --------------------------------------------------------------------

        if product_results:
            product_lines = []

            for product, _score in product_results:
                if product is None:
                    continue

                line = (
                    f"- {product.name}: "
                    f"{product.price} {product.currency}"
                )

                if product.discount_percent:
                    line += (
                        f" "
                        f"({product.discount_percent:g}% off)"
                    )

                if product.description:
                    line += (
                        f" - {product.description}"
                    )

                product_lines.append(
                    line
                )

            if product_lines:
                parts.append(
                    "Relevant products/services you can sell:\n"
                    + "\n".join(product_lines)
                )

        return "\n\n".join(
            part
            for part in parts
            if part
            and str(part).strip()
        )

    # ========================================================================
    # Conversation prompt
    # ========================================================================

    @staticmethod
    def _build_prompt(
        history: list[Message],
        latest_text: str,
        current_message_id=None,
    ) -> str:
        """Build conversation prompt without duplicating current turn."""

        lines: list[str] = []

        for message in history:
            # ---------------------------------------------------------------
            # Do not add current inbound message twice.
            # ---------------------------------------------------------------

            if (
                current_message_id is not None
                and message.id == current_message_id
            ):
                continue

            # ---------------------------------------------------------------
            # Customer
            # ---------------------------------------------------------------

            if message.role == MessageRole.USER:
                if message.content:
                    lines.append(
                        f"Customer: {message.content}"
                    )

            # ---------------------------------------------------------------
            # AI/agent
            # ---------------------------------------------------------------

            elif message.role == MessageRole.AGENT:
                if message.content:
                    lines.append(
                        f"You: {message.content}"
                    )

        # --------------------------------------------------------------------
        # Current user turn exactly once.
        # --------------------------------------------------------------------

        if latest_text:
            lines.append(
                f"Customer: {latest_text}"
            )

        # --------------------------------------------------------------------
        # Model response marker.
        # --------------------------------------------------------------------

        lines.append(
            "You:"
        )

        return "\n".join(lines)

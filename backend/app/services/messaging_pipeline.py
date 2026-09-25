"""MessagingPipeline — production message orchestration.

Flow for handle_incoming():

  1. Parse the platform webhook payload.
  2. Get/create the conversation.
  3. Store the inbound message.
  4. Mark the message as read / typing where supported.
  5. Get/create the platform customer.
  6. Apply human-assignment, auto-reply, business-hours and plan-limit rules.
  7. IMAGE/VOICE messages are processed into useful text.
  8. Select the appropriate agent.
  9. Retrieve knowledge, memory and product context.
 10. Build the conversation prompt without duplicating the current message.
 11. Generate the AI response.
 12. Store the outgoing message.
 13. Send the response through the same platform.
 14. Send a product image ONLY when the customer explicitly asks
     to see/show/send a product image.

Important production behavior:

- Gemini/provider retries are handled by the AI provider.
- This pipeline does NOT retry the entire message because doing so could
  duplicate side effects such as orders, receipts or other tools.
- Routing failure and response-generation failure are logged separately.
- If AI routing fails, the pipeline falls back to an already-known/default
  agent where possible instead of unnecessarily abandoning the conversation.
- Payment receipt images are never treated as automatic payment confirmation.
- Platform media downloads are normalized before being passed to the AI
  provider because adapters may return `(bytes, mime_type)` tuples.
- Explicit product-image requests are handled by application logic rather
  than asking the LLM to physically send the image.
- Normal product searches NEVER cause product images to be sent automatically.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan_limits import check_message_limit
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
from app.services.notification_service import NotificationService
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


# ===========================================================================
# Order / payment constants
# ===========================================================================

_AWAITING_PAYMENT_STATUSES = {
    PaymentStatus.UNPAID,
    PaymentStatus.AWAITING_CONFIRMATION,
}

_CLOSED_ORDER_STATUSES = {
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.DELIVERED,
}


# ===========================================================================
# Product image intent
# ===========================================================================

# IMPORTANT:
#
# This detector is ONLY for deciding whether the customer explicitly wants
# a product image.
#
# It is NOT used to decide whether a product is relevant to the conversation.
#
# Normal product questions such as:
#
#   "How much is the hoodie?"
#   "Do you have the black hoodie?"
#   "Is the hoodie available?"
#   "What sizes does the hoodie come in?"
#   "Show me the price"
#
# must NOT cause an image to be sent.
#
# Explicit visual requests such as:
#
#   "Send me a picture of the hoodie"
#   "Show me an image of the black hoodie"
#   "Can I see the hoodie?"
#   "What does the hoodie look like?"
#
# may cause an image to be sent.
_PRODUCT_IMAGE_INTENT_PATTERNS = (
    # "send/show/share/get/view + image word"
    r"\b(?:send|show|see|view|get|share)\b.{0,50}\b"
    r"(?:photo|picture|pic|image|images|photos|pictures)\b",

    # "image word + send/show/share/get/view"
    r"\b(?:photo|picture|pic|image|images|photos|pictures)\b"
    r".{0,50}\b(?:send|show|see|view|get|share)\b",

    # "Can I see the hoodie?"
    # This intentionally requires "see/view" to be followed by an actual
    # object/context rather than matching every "can I see..." statement.
    r"\bcan\s+i\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    # "Could I see the hoodie?"
    r"\bcould\s+i\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    # "Let me see the hoodie"
    r"\b(?:let|allow)\s+me\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    # "I want to see the hoodie"
    r"\bi\s+(?:want|would\s+like|d['’]like)\s+to\s+(?:see|view)\s+"
    r"(?:it|that|this|the\s+\w+|your\s+\w+|a\s+\w+|an\s+\w+)\b",

    # "What does the hoodie look like?"
    r"\bwhat\s+(?:does|do)\b.{0,60}\b"
    r"(?:look\s+like|looks\s+like)\b",

    # "Can you show me the hoodie?"
    r"\bcan\s+you\s+show\s+me\b.{0,50}\b"
    r"(?:the|this|that|your|a|an)\b",

    # "Could you show me the hoodie?"
    r"\bcould\s+you\s+show\s+me\b.{0,50}\b"
    r"(?:the|this|that|your|a|an)\b",

    # "Can you send the hoodie?"
    #
    # This pattern is deliberately NOT enough by itself to send an image
    # unless the message also contains an image-related word.
    r"\bcan\s+you\s+send\b.{0,40}\b"
    r"(?:photo|picture|pic|image|images|photos|pictures)\b",

    # Explicit "show me a photo/picture/image"
    r"\bshow\s+me\b.{0,50}\b"
    r"(?:photo|picture|pic|image|images|photos|pictures)\b",

    # Explicit "show me what it looks like"
    r"\bshow\s+me\b.{0,50}\b"
    r"(?:what\s+it\s+looks\s+like|what\s+that\s+looks\s+like)\b",
)


def _is_product_image_request(text: str | None) -> bool:
    """Return True only when the customer explicitly requests a product image.

    The function intentionally avoids broad patterns such as:

        "show me"
        "let me see"
        "can you show"

    by themselves because those phrases can also refer to prices, sizes,
    colors, product details, availability, etc.

    Examples that should return True:

        "Send me a picture of the hoodie."
        "Show me an image of the black hoodie."
        "Can I see the hoodie?"
        "Could I see the red sneakers?"
        "What does the hoodie look like?"
        "Show me a photo of the product."

    Examples that should return False:

        "How much is the hoodie?"
        "Do you have a black hoodie?"
        "Show me the price."
        "Show me available sizes."
        "Can you show me the price?"
        "Is the hoodie available?"
    """

    if not text:
        return False

    normalized = " ".join(
        str(text).strip().lower().split()
    )

    if not normalized:
        return False

    for pattern in _PRODUCT_IMAGE_INTENT_PATTERNS:
        if re.search(
            pattern,
            normalized,
            flags=re.IGNORECASE,
        ):
            return True

    return False


def _normalize_product_search_text(
    text: str | None,
) -> str:
    """Remove image-request wording while preserving product wording.

    Example:

        "Can you send me a photo of the black hoodie?"

    becomes approximately:

        "black hoodie"

    The cleaned text is used as an additional product-search query.
    """

    if not text:
        return ""

    normalized = " ".join(
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

    cleaned = normalized

    for pattern in replacements:
        cleaned = re.sub(
            pattern,
            " ",
            cleaned,
            flags=re.IGNORECASE,
        )

    cleaned = re.sub(
        r"\s+",
        " ",
        cleaned,
    ).strip()

    return cleaned


def _product_has_image(product: Product | None) -> bool:
    """Return True when a product has at least one usable image URL."""

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
    """Build a useful caption for a product image."""

    lines = [
        f"{product.name} — {product.price} {product.currency}"
    ]

    variants = product.variants or []

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
            product.description[:200]
        )

    return "\n".join(lines)[:1024]


# ===========================================================================
# Non-text fallbacks
# ===========================================================================

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


# ===========================================================================
# Business hours
# ===========================================================================

_WEEKDAY_KEYS = [
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
]


def _after_hours_reply(
    settings: dict,
) -> str | None:
    """Return an after-hours message when business hours are configured."""

    business_hours = settings.get(
        "business_hours"
    )

    if not isinstance(
        business_hours,
        dict,
    ):
        return None

    if not business_hours.get(
        "enabled"
    ):
        return None

    try:
        import zoneinfo

        timezone_name = business_hours.get(
            "timezone",
            "UTC",
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

        window = hours.get(
            today_key
        )

        if not window or len(window) < 2:
            is_open = False
        else:
            open_str = str(window[0])
            close_str = str(window[1])

            open_time = datetime.strptime(
                open_str,
                "%H:%M",
            ).time()

            close_time = datetime.strptime(
                close_str,
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
            (
                "Malformed business_hours settings; "
                "ignoring business-hours rule"
            ),
            exc_info=True,
        )

        return None

    if is_open:
        return None

    return business_hours.get(
        "message",
        (
            "Thanks for reaching out! We're currently outside business "
            "hours and will reply as soon as we're back."
        ),
    )


# ===========================================================================
# Media normalization
# ===========================================================================


def _normalize_downloaded_media(
    media_result: Any,
    default_mime_type: str,
) -> tuple[bytes, str]:
    """Normalize platform media into `(bytes, mime_type)`."""

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
                possible_mime = item.strip()

                if "/" in possible_mime:
                    mime_type = possible_mime

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
            possible_mime = (
                possible_mime.strip()
            )

            if possible_mime:
                mime_type = possible_mime

    if not media_bytes:
        raise ValueError(
            "Platform returned media, but no bytes could be extracted "
            f"from type {type(media_result).__name__}"
        )

    final_mime_type = (
        mime_type
        or default_mime_type
    )

    return (
        media_bytes,
        final_mime_type,
    )


# ===========================================================================
# MessagingPipeline
# ===========================================================================


class MessagingPipeline:
    """Orchestrates inbound platform messages."""

    def __init__(
        self,
        db: AsyncSession,
    ):
        self.db = db

        self.conversation_service = (
            ConversationService(db)
        )

        self.router_service = (
            RouterService(db)
        )

        self.knowledge_service = (
            KnowledgeService(db)
        )

        self.memory_service = (
            MemoryService(db)
        )

        self.product_service = (
            ProductService(db)
        )

        self.customer_service = (
            CustomerService(db)
        )

        self.order_service = (
            OrderService(db)
        )

    # =======================================================================
    # Main entry point
    # =======================================================================

    async def handle_incoming(
        self,
        owner: User,
        integration: PlatformIntegration,
        raw_payload: dict,
    ) -> None:
        """Process one incoming platform webhook/message."""

        adapter = build_adapter(
            integration
        )

        try:
            # ----------------------------------------------------------------
            # 1. Parse incoming platform payload
            # ----------------------------------------------------------------

            incoming = adapter.parse_incoming(
                raw_payload
            )

            if incoming is None:
                logger.debug(
                    (
                        "Platform adapter ignored incoming payload "
                        "for integration %s"
                    ),
                    integration.id,
                )

                return

            logger.info(
                (
                    "Processing incoming message: platform=%s "
                    "conversation=%s message_type=%s "
                    "external_message_id=%s"
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
            # 4. Mark message as read / typing
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
                        (
                            "mark_read failed for message %s"
                        ),
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
            # 6. Human takeover / auto-reply
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
            # 7. Business-hours rule
            # ----------------------------------------------------------------

            after_hours_reply = _after_hours_reply(
                integration.settings
            )

            if after_hours_reply is not None:
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
            # 8. Plan message limit
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
            # 9. Convert image / voice into useful text
            # ----------------------------------------------------------------

            effective_text = incoming.text

            # ----------------------------------------------------------------
            # IMAGE
            # ----------------------------------------------------------------

            if (
                incoming.message_type
                == MessageType.IMAGE
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

            # ----------------------------------------------------------------
            # VOICE
            # ----------------------------------------------------------------

            elif (
                incoming.message_type
                == MessageType.VOICE
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
                                "Failed to send voice transcription "
                                "fallback for conversation %s"
                            ),
                            conversation.id,
                            exc_info=True,
                        )

                    return

            # ----------------------------------------------------------------
            # Detect explicit product image request.
            #
            # IMPORTANT:
            #
            # This is application-level intent detection.
            #
            # The LLM does NOT physically send the image.
            #
            # The backend sends the image through the platform adapter only
            # after the AI text response has been successfully sent.
            # ----------------------------------------------------------------

            wants_product_image = (
                _is_product_image_request(
                    effective_text
                )
            )

            if wants_product_image:
                logger.info(
                    (
                        "Explicit product image request detected "
                        "for conversation %s: %s"
                    ),
                    conversation.id,
                    effective_text,
                )

            # ----------------------------------------------------------------
            # 10. Select agent
            # ----------------------------------------------------------------

            agent = None

            if effective_text:
                try:
                    logger.info(
                        "Routing message for conversation %s",
                        conversation.id,
                    )

                    agent = await self.router_service.route(
                        owner.id,
                        effective_text,
                    )

                    logger.info(
                        (
                            "AI routing selected agent %s "
                            "for conversation %s"
                        ),
                        getattr(
                            agent,
                            "id",
                            None,
                        ),
                        conversation.id,
                    )

                except Exception:
                    logger.error(
                        (
                            "AI routing failed for conversation %s; "
                            "falling back to deterministic agent"
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
                                "Deterministic agent fallback also failed "
                                "for conversation %s"
                            ),
                            conversation.id,
                            exc_info=True,
                        )

                        agent = None

            else:
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
                            "Unable to select an agent "
                            "for conversation %s"
                        ),
                        conversation.id,
                        exc_info=True,
                    )

                    agent = None

            # ----------------------------------------------------------------
            # 11. Generate response + product context
            # ----------------------------------------------------------------

            if agent is None:
                reply_text = (
                    "Sorry, we're unable to respond right now. "
                    "A team member will follow up shortly."
                )

                top_product = None
                requested_product = None

            else:
                try:
                    logger.info(
                        (
                            "Generating AI reply: conversation=%s "
                            "agent=%s message_type=%s"
                        ),
                        conversation.id,
                        agent.id,
                        incoming.message_type,
                    )

                    (
                        reply_text,
                        top_product,
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
                            "AI reply generation failed for conversation %s "
                            "using agent %s"
                        ),
                        conversation.id,
                        agent.id,
                        exc_info=True,
                    )

                    reply_text = (
                        "Sorry, something went wrong on our end. "
                        "We'll follow up shortly."
                    )

                    top_product = None
                    requested_product = None

            # ----------------------------------------------------------------
            # 12. Store outgoing message
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
            # 13. Send final text response
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

                # Do not regenerate or retry the entire pipeline.
                return

            # ----------------------------------------------------------------
            # 14. Send product image ONLY when explicitly requested
            # ----------------------------------------------------------------
            #
            # IMPORTANT PRODUCTION RULE:
            #
            # top_product is useful for AI/product context.
            #
            # It MUST NOT be used as a reason to send an image.
            #
            # Therefore:
            #
            #     wants_product_image
            #             AND
            #     requested_product exists
            #             AND
            #     requested_product has an image
            #
            # are ALL required.
            #
            # This prevents:
            #
            # "How much is the hoodie?"
            #
            # from sending:
            #
            # "hoodie.jpg"
            #
            # while still allowing:
            #
            # "Send me a picture of the hoodie."
            #
            # to send the image.
            # ----------------------------------------------------------------

            if (
                wants_product_image
                and requested_product is not None
                and _product_has_image(
                    requested_product
                )
            ):
                try:
                    image_url = (
                        requested_product.images[0]
                    )

                    caption = (
                        _build_product_photo_caption(
                            requested_product
                        )
                    )

                    logger.info(
                        (
                            "Sending explicitly requested product image: "
                            "conversation=%s product=%s image_url=%s"
                        ),
                        conversation.id,
                        requested_product.id,
                        image_url,
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
                            "Failed to send requested product photo "
                            "for product %s"
                        ),
                        requested_product.id,
                        exc_info=True,
                    )

            elif wants_product_image:
                logger.info(
                    (
                        "Customer explicitly requested a product image, "
                        "but no matching product with a usable image "
                        "was found: conversation=%s"
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

    # =======================================================================
    # Plan limit
    # =======================================================================

    async def _handle_message_limit_reached(
        self,
        owner: User,
        integration: PlatformIntegration,
        conversation: Conversation,
        adapter: Any,
        plan: Any,
    ) -> None:
        """Send a plan-limit response and notify owner once per 24 hours."""

        reply = (
            "Thanks for your message! We've reached our messaging limit "
            "for this month — a team member will get back to you as soon "
            "as possible."
        )

        await self.conversation_service.add_message(
            conversation,
            role=MessageRole.SYSTEM,
            content=reply,
        )

        await self.db.commit()

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

        try:
            since = (
                datetime.now().astimezone()
                - timedelta(hours=24)
            )

            existing_notification = await self.db.scalar(
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

            if existing_notification is None:
                notification_service = (
                    NotificationService(
                        self.db
                    )
                )

                await notification_service.create_notification(
                    owner_id=owner.id,
                    notification_type=(
                        NotificationType.PLAN_LIMIT_REACHED
                    ),
                    title="Monthly messaging limit reached",
                    message=(
                        "Your monthly messaging limit has been reached. "
                        "Customers can still be handled manually."
                    ),
                )

                await self.db.commit()

        except Exception:
            logger.warning(
                (
                    "Failed to create plan-limit notification "
                    "for owner %s"
                ),
                owner.id,
                exc_info=True,
            )

    # =======================================================================
    # Receipt order lookup
    # =======================================================================

    async def _find_receipt_target_order(
        self,
        owner_id,
        customer_id,
    ):
        """Find newest customer order awaiting payment."""

        orders = await self.order_service.list_orders(
            owner_id,
            customer_id=customer_id,
        )

        for order in orders:
            if order.status in _CLOSED_ORDER_STATUSES:
                continue

            if (
                order.payment_status
                in _AWAITING_PAYMENT_STATUSES
            ):
                return order

        return None

    # =======================================================================
    # Media MIME helpers
    # =======================================================================

    @staticmethod
    def _get_media_mime_type(
        incoming,
        default: str,
    ) -> str:
        """Get MIME type from platform metadata."""

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
            mime_type = (
                mime_type.strip().lower()
            )

            if mime_type:
                return mime_type

        return default

    # =======================================================================
    # Image handling
    # =======================================================================

    async def _handle_image_message(
        self,
        owner: User,
        conversation: Conversation,
        customer,
        incoming,
        adapter,
        inbound_message: Message,
    ) -> tuple[bool, str | None]:
        """Download and understand an incoming image."""

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
                    default_mime_type="image/jpeg",
                )
            )

            logger.info(
                (
                    "Analyzing image for conversation %s "
                    "with mime_type=%s"
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
                    "Image analysis returned empty description"
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

            # ---------------------------------------------------------------
            # Payment receipt detection.
            #
            # IMPORTANT:
            #
            # Classification alone does NOT confirm payment.
            # The actual payment still needs verification.
            # ---------------------------------------------------------------

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

                    normalized_classification = (
                        str(classification)
                        .strip()
                        .lower()
                        .replace(
                            " ",
                            "_",
                        )
                        .replace(
                            "-",
                            "_",
                        )
                    )

                    is_payment_receipt = (
                        "payment_receipt"
                        in normalized_classification
                        or "bank_transfer"
                        in normalized_classification
                        or normalized_classification
                        == (
                            "payment_receipt_or_bank_transfer_"
                            "confirmation"
                        )
                    )

                except Exception:
                    logger.warning(
                        (
                            "Image classification failed for "
                            "conversation %s; treating image as "
                            "a normal image"
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
                    (
                        "Failed to send image fallback "
                        "acknowledgement"
                    ),
                    exc_info=True,
                )

            return (
                True,
                None,
            )

    # =======================================================================
    # Voice handling
    # =======================================================================

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
                    default_mime_type="audio/ogg",
                )
            )

            logger.info(
                "Transcribing voice message with mime_type=%s",
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

            inbound_message.content = (
                transcript
            )

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

            fallback_text = (
                str(incoming.text).strip()
                if incoming.text
                else ""
            )

            return (
                fallback_text
                or None
            )

    # =======================================================================
    # Deterministic agent selection
    # =======================================================================

    async def _pick_agent_without_ai(
        self,
        owner_id,
        conversation: Conversation,
        integration: PlatformIntegration,
    ) -> Agent:
        """Select an agent without calling Gemini."""

        # -------------------------------------------------------------------
        # 1. Existing conversation assignment
        # -------------------------------------------------------------------

        if conversation.agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == conversation.agent_id,
                    Agent.owner_id == owner_id,
                )
            )

            agent = (
                result.scalar_one_or_none()
            )

            if agent is not None:
                return agent

        # -------------------------------------------------------------------
        # 2. Integration default agent
        # -------------------------------------------------------------------

        default_agent_id = (
            integration.default_agent_id
        )

        if default_agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == default_agent_id,
                    Agent.owner_id == owner_id,
                )
            )

            agent = (
                result.scalar_one_or_none()
            )

            if agent is not None:
                return agent

        # -------------------------------------------------------------------
        # 3. First active owner agent
        # -------------------------------------------------------------------

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

    # =======================================================================
    # Product image matching
    # =======================================================================

    async def _find_requested_product(
        self,
        owner_id,
        query: str | None,
    ) -> Product | None:
        """Find the product the customer is explicitly asking to see.

        Product search is attempted twice:

        1. Original customer wording.
        2. Cleaned product wording with image-request language removed.

        IMPORTANT:

        This method selects the best matching product first.

        It does NOT silently replace a matching product without an image
        with an unrelated product that happens to have an image.

        That prevents this bad behavior:

            Customer asks for Product A.
            Product A has no image.
            Search also finds Product B with an image.
            System sends Product B.

        Instead, if the requested product has no image, no product image
        is sent.
        """

        if not query:
            return None

        search_queries: list[str] = []

        original = str(
            query
        ).strip()

        if original:
            search_queries.append(
                original
            )

        cleaned = (
            _normalize_product_search_text(
                original
            )
        )

        if (
            cleaned
            and cleaned.lower()
            != original.lower()
        ):
            search_queries.append(
                cleaned
            )

        best_product: Product | None = None
        best_score: float = float("-inf")

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
                        "Product search failed while finding "
                        "requested product: query=%s"
                    ),
                    search_query,
                    exc_info=True,
                )

                continue

            for product, score in results:
                if product is None:
                    continue

                numeric_score = float(
                    score or 0
                )

                if numeric_score > best_score:
                    best_score = numeric_score
                    best_product = product

            # The cleaned query is normally more useful because it removes
            # words such as "send", "photo", "show", etc.
            #
            # Once we have a result from the cleaned query, we prefer that
            # product rather than continuing into potentially unrelated
            # matches from the original sentence.
            if (
                cleaned
                and search_query == cleaned
                and best_product is not None
            ):
                break

        if best_product is not None:
            logger.info(
                (
                    "Requested product matched: product=%s "
                    "score=%s query=%s has_image=%s"
                ),
                best_product.id,
                best_score,
                query,
                _product_has_image(best_product),
            )

        return best_product

    # =======================================================================
    # Build AI response
    # =======================================================================

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
        """Build context and generate the AI reply.

        Returns:

            reply_text
            top_semantic_product
            explicitly_requested_product

        IMPORTANT:

        `top_semantic_product` is contextual information for the AI.

        It is NOT a signal to send a product image.

        Product-image delivery is controlled exclusively by:

            wants_product_image
            requested_product
            _product_has_image(requested_product)
        """

        if not effective_text:
            return (
                _NON_TEXT_ACKNOWLEDGEMENTS.get(
                    incoming.message_type,
                    "Got it, thanks!",
                ),
                None,
                None,
            )

        # -------------------------------------------------------------------
        # RAG: knowledge
        # -------------------------------------------------------------------

        knowledge_results = (
            await self.knowledge_service.search(
                owner.id,
                effective_text,
                agent_id=agent.id,
                top_k=3,
            )
        )

        # -------------------------------------------------------------------
        # RAG: memory
        # -------------------------------------------------------------------

        memory_results = (
            await self.memory_service.search(
                owner.id,
                effective_text,
                agent_id=agent.id,
                top_k=3,
            )
        )

        # -------------------------------------------------------------------
        # Product search
        #
        # This is ALWAYS allowed for product-related questions.
        #
        # However, product search alone NEVER causes an image to be sent.
        # -------------------------------------------------------------------

        product_results = (
            await self.product_service.search(
                owner.id,
                effective_text,
                top_k=3,
            )
        )

        # -------------------------------------------------------------------
        # Explicit requested product.
        #
        # Only perform the extra requested-product lookup when the customer
        # actually requested an image.
        # -------------------------------------------------------------------

        requested_product = None

        if wants_product_image:
            requested_product = (
                await self._find_requested_product(
                    owner.id,
                    effective_text,
                )
            )

        # -------------------------------------------------------------------
        # Conversation history.
        # -------------------------------------------------------------------

        history = (
            await self.conversation_service.get_recent_messages(
                conversation.id,
                limit=11,
            )
        )

        # -------------------------------------------------------------------
        # System instruction
        # -------------------------------------------------------------------

        system_instruction = (
            self._build_system_instruction(
                agent=agent,
                knowledge_results=knowledge_results,
                memory_results=memory_results,
                product_results=product_results,
            )
        )

        # -------------------------------------------------------------------
        # Messaging capability instruction
        #
        # This is important because Gemini may otherwise believe that it
        # physically controls the messaging platform.
        #
        # The backend is responsible for sending product images.
        # -------------------------------------------------------------------

        messaging_capability_instruction = """
Messaging capabilities:

- You are operating inside a customer messaging platform.
- The application can send product images separately from your text reply.
- Do not say that you cannot send images.
- Do not say that the chat system does not support images.
- Do not say that you wish you could send a photo.
- Do not invent an image URL.
- Do not claim that an image was delivered unless the application has
  actually sent it.
- For normal product questions, answer normally and do not suggest that
  an image will be sent unless the customer explicitly asked to see one.
""".strip()

        system_instruction = (
            f"{system_instruction}\n\n"
            f"{messaging_capability_instruction}"
        ).strip()

        # -------------------------------------------------------------------
        # Explicit product image request.
        #
        # The backend sends the image separately.
        #
        # Gemini only needs to produce natural text.
        # -------------------------------------------------------------------

        if requested_product is not None:
            system_instruction = (
                f"{system_instruction}\n\n"
                "PRODUCT IMAGE REQUEST:\n"
                "The customer has explicitly requested to see a product "
                "image. The application will attempt to send the matching "
                "product image separately after your text response. "
                "Respond naturally and briefly. Do not say that you cannot "
                "send images. Do not claim that the image has already been "
                "delivered. Do not invent an image URL or attachment.\n"
                f"Requested product: {requested_product.name}"
            )

        # -------------------------------------------------------------------
        # Conversation prompt
        # -------------------------------------------------------------------

        prompt = self._build_prompt(
            history=history,
            latest_text=effective_text,
            current_message_id=inbound_message.id,
        )

        # -------------------------------------------------------------------
        # Customer-aware tool calling.
        # -------------------------------------------------------------------

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

            reply_text = (
                await self.router_service.ai_provider.generate_with_tools(
                    prompt,
                    tools=default_tool_definitions(),
                    tool_executor=tool_executor,
                    system_instruction=system_instruction,
                    temperature=agent.temperature,
                )
            )

        else:
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

        # -------------------------------------------------------------------
        # Normal semantic product context.
        #
        # IMPORTANT:
        #
        # This does NOT mean an image should be sent.
        #
        # It simply identifies the most relevant product for the AI's
        # response/context.
        # -------------------------------------------------------------------

        top_product = None

        if product_results:
            best_product, _best_score = (
                product_results[0]
            )

            if best_product is not None:
                top_product = best_product

        # -------------------------------------------------------------------
        # Explicit image request takes priority for requested-product
        # context.
        # -------------------------------------------------------------------

        if requested_product is not None:
            top_product = requested_product

        return (
            reply_text,
            top_product,
            requested_product,
        )

    # =======================================================================
    # System prompt
    # =======================================================================

    @staticmethod
    def _build_system_instruction(
        agent,
        knowledge_results,
        memory_results,
        product_results,
    ) -> str:
        """Build the system instruction supplied to the AI model."""

        parts: list[str] = []

        if agent.instructions:
            parts.append(
                str(agent.instructions)
            )

        # -------------------------------------------------------------------
        # Knowledge
        # -------------------------------------------------------------------

        if knowledge_results:
            knowledge_lines = "\n".join(
                f"- {chunk.content}"
                for chunk, _score
                in knowledge_results
                if chunk.content
            )

            if knowledge_lines:
                parts.append(
                    "Relevant knowledge base entries:\n"
                    f"{knowledge_lines}"
                )

        # -------------------------------------------------------------------
        # Memory
        # -------------------------------------------------------------------

        if memory_results:
            memory_lines = "\n".join(
                f"- {entry.content}"
                for entry, _score
                in memory_results
                if entry.content
            )

            if memory_lines:
                parts.append(
                    "Relevant things you know/remember:\n"
                    f"{memory_lines}"
                )

        # -------------------------------------------------------------------
        # Products
        # -------------------------------------------------------------------

        if product_results:
            product_lines = "\n".join(
                (
                    f"- {product.name}: "
                    f"{product.price} {product.currency}"
                    + (
                        f" ({product.discount_percent:g}% off)"
                        if product.discount_percent
                        else ""
                    )
                    + (
                        f" - {product.description}"
                        if product.description
                        else ""
                    )
                )
                for product, _score
                in product_results
            )

            if product_lines:
                parts.append(
                    "Relevant products/services you can sell:\n"
                    f"{product_lines}"
                )

        return "\n\n".join(
            part.strip()
            for part in parts
            if part
            and str(part).strip()
        )

    # =======================================================================
    # Conversation prompt
    # =======================================================================

    @staticmethod
    def _build_prompt(
        history: list[Message],
        latest_text: str,
        current_message_id=None,
    ) -> str:
        """Build conversation prompt without duplicating current turn."""

        lines: list[str] = []

        for message in history:
            # ----------------------------------------------------------------
            # Skip current inbound message.
            # ----------------------------------------------------------------

            if (
                current_message_id is not None
                and message.id == current_message_id
            ):
                continue

            # ----------------------------------------------------------------
            # Customer messages.
            # ----------------------------------------------------------------

            if message.role == MessageRole.USER:
                if message.content:
                    lines.append(
                        f"Customer: {message.content}"
                    )

            # ----------------------------------------------------------------
            # Agent messages.
            # ----------------------------------------------------------------

            elif message.role == MessageRole.AGENT:
                if message.content:
                    lines.append(
                        f"You: {message.content}"
                    )

        # --------------------------------------------------------------------
        # Add current user turn exactly once.
        # --------------------------------------------------------------------

        if latest_text:
            lines.append(
                f"Customer: {latest_text}"
            )

        # --------------------------------------------------------------------
        # Ask model to produce next assistant response.
        # --------------------------------------------------------------------

        lines.append(
            "You:"
        )

        return "\n".join(
            lines
        )

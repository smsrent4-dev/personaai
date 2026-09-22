"""
MessagingPipeline — production orchestration for incoming platform messages.

The pipeline coordinates the previously implemented services without
reimplementing their business logic.

Flow for handle_incoming():

    1. adapter.parse_incoming()
    2. ConversationService.get_or_create_conversation()
    3. Store incoming message
    4. Resolve customer identity
    5. Apply human/auto-reply/business-hours/plan guards
    6. Analyze IMAGE/VOICE media when applicable
    7. Resolve the conversation's agent
    8. Compute one embedding when semantic retrieval is actually needed
    9. Retrieve knowledge, memories, and products
   10. Build compact prompt + recent history
   11. Generate reply, using tools only when required
   12. Store outgoing message
   13. Send product media when relevant
   14. Send final text response

Performance principles:

- Do not perform AI work for messages that do not need it.
- Do not embed the same query multiple times.
- Do not route an already-routed conversation repeatedly.
- Do not invoke tool-calling for ordinary conversational messages.
- Do not duplicate the current inbound message in the generation prompt.
- Keep the same AsyncSession sequential; do not concurrently operate on it.
"""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.plan_limits import check_message_limit
from app.models.agent import Agent, AgentStatus
from app.models.conversation import Conversation
from app.models.integration import PlatformIntegration
from app.models.message import Message, MessageRole, MessageType
from app.models.notification import Notification, NotificationType
from app.models.order import Order, OrderStatus, PaymentStatus
from app.models.product import Product
from app.models.user import User
from app.services.conversation_service import ConversationService
from app.services.customer_service import CustomerService
from app.services.knowledge import KnowledgeService
from app.services.memory_service import MemoryService
from app.services.notification_service import NotificationService
from app.services.order_service import OrderService
from app.services.platforms.base import IncomingMessage
from app.services.platforms.registry import build_adapter
from app.services.product_service import ProductService
from app.services.router_service import RouterService
from app.services.tools import ToolContext, default_tool_definitions, execute_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order/payment safety
# ---------------------------------------------------------------------------

_AWAITING_PAYMENT_STATUSES = {
    PaymentStatus.UNPAID,
    PaymentStatus.AWAITING_CONFIRMATION,
}

_CLOSED_ORDER_STATUSES = {
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.DELIVERED,
}


# ---------------------------------------------------------------------------
# Product media
# ---------------------------------------------------------------------------

# ProductService returns best-effort semantic matches. This threshold prevents
# an unrelated product from being sent for messages such as "hello" or
# "what are your opening hours".
PRODUCT_PHOTO_MIN_SCORE = 0.5


def _build_product_photo_caption(product: Product) -> str:
    """
    Build a useful caption for an automatically sent product image.

    Includes:
    - product name
    - price/currency
    - variants
    - inventory state
    - short description

    The result is capped to the platform caption limit.
    """
    lines = [
        f"{product.name} — {product.price} {product.currency}",
    ]

    variant_names = [
        variant.get("name")
        for variant in (product.variants or [])
        if isinstance(variant, dict) and variant.get("name")
    ]

    if variant_names:
        lines.append(f"Available: {', '.join(variant_names)}")

    if product.inventory is not None:
        lines.append(
            "In stock"
            if product.inventory > 0
            else "Currently out of stock"
        )

    if product.description:
        lines.append(product.description[:200])

    return "\n".join(lines)[:1024]


# ---------------------------------------------------------------------------
# Non-text fallbacks
# ---------------------------------------------------------------------------

_NON_TEXT_ACKNOWLEDGEMENTS = {
    MessageType.IMAGE: (
        "Thanks for the image - I've received it and will follow up shortly."
    ),
    MessageType.DOCUMENT: (
        "Thanks for the document - I've received it and will follow up shortly."
    ),
    MessageType.VOICE: (
        "Thanks for the voice message - I've received it and will follow up shortly."
    ),
    MessageType.LOCATION: (
        "Thanks for sharing your location - noted."
    ),
    MessageType.VIDEO: (
        "Thanks for the video - I've received it and will follow up shortly."
    ),
    MessageType.CONTACT: (
        "Thanks for sharing that contact - noted."
    ),
    MessageType.OTHER: "Got it, thanks!",
}


# ---------------------------------------------------------------------------
# Business hours
# ---------------------------------------------------------------------------

_WEEKDAY_KEYS = [
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
]


def _after_hours_reply(settings: dict) -> str | None:
    """
    Return the configured after-hours message when the business is closed.

    Expected configuration:

        {
            "enabled": true,
            "timezone": "Africa/Lagos",
            "hours": {
                "mon": ["09:00", "17:00"],
                "tue": ["09:00", "17:00"]
            },
            "message": "We're currently closed..."
        }

    Malformed configuration fails open so a configuration mistake cannot
    accidentally disable all automated replies.
    """
    business_hours = settings.get("business_hours")

    if not business_hours or not business_hours.get("enabled"):
        return None

    try:
        import zoneinfo

        timezone_name = business_hours.get("timezone", "UTC")
        tz = zoneinfo.ZoneInfo(timezone_name)

        now = datetime.now(tz)
        today_key = _WEEKDAY_KEYS[now.weekday()]

        window = business_hours.get("hours", {}).get(today_key)

        if not window:
            is_open = False
        else:
            open_str, close_str = window[0], window[1]

            open_time = datetime.strptime(
                open_str,
                "%H:%M",
            ).time()

            close_time = datetime.strptime(
                close_str,
                "%H:%M",
            ).time()

            is_open = open_time <= now.time() <= close_time

    except Exception:
        logger.warning(
            "Malformed business_hours settings; ignoring",
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


class MessagingPipeline:
    """
    Orchestrates incoming messages through the PersonaAI messaging stack.

    This class intentionally does not contain domain logic belonging to
    ConversationService, RouterService, KnowledgeService, MemoryService,
    ProductService, OrderService, or CustomerService.
    """

    # Keep generation history intentionally small. Larger histories increase
    # prompt size and therefore model latency/cost.
    HISTORY_LIMIT = 6

    # Messages in this set do not require semantic retrieval.
    _SIMPLE_MESSAGES = frozenset(
        {
            "hi",
            "hello",
            "hey",
            "hiya",
            "yo",
            "good morning",
            "good afternoon",
            "good evening",
            "thanks",
            "thank you",
            "thank you so much",
            "okay",
            "ok",
            "alright",
            "great",
            "nice",
            "cool",
            "sure",
            "yes",
            "no",
            "bye",
            "goodbye",
        }
    )

    # These are transactional/customer-account actions that justify exposing
    # the slower tool-calling loop to Gemini.
    #
    # Generic product-information questions do NOT automatically enter the
    # tool loop because ProductService already supplies product context.
    _TOOL_PHRASES = (
        "my order",
        "my orders",
        "order status",
        "track my order",
        "track order",
        "where is my order",
        "order number",
        "place an order",
        "make an order",
        "create an order",
        "buy this",
        "i want to buy",
        "i want to order",
        "add to cart",
        "purchase",
        "checkout",
        "payment status",
        "payment confirmation",
        "i paid",
        "i have paid",
        "payment receipt",
        "cancel my order",
        "cancel order",
        "refund my order",
        "return my order",
        "delivery status",
        "shipping status",
    )

    def __init__(self, db: AsyncSession):
        self.db = db

        self.conversation_service = ConversationService(db)
        self.router_service = RouterService(db)
        self.knowledge_service = KnowledgeService(db)
        self.memory_service = MemoryService(db)
        self.product_service = ProductService(db)
        self.customer_service = CustomerService(db)
        self.order_service = OrderService(db)

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    async def handle_incoming(
        self,
        owner: User,
        integration: PlatformIntegration,
        raw_payload: dict,
    ) -> None:
        """
        Process one incoming platform message from start to finish.
        """
        pipeline_started = time.perf_counter()

        adapter = build_adapter(integration)

        try:
            stage_started = time.perf_counter()

            incoming = adapter.parse_incoming(raw_payload)

            self._log_stage(
                "parse_incoming",
                stage_started,
                integration.platform,
            )

            if incoming is None:
                return

            # ---------------------------------------------------------------
            # Conversation
            # ---------------------------------------------------------------

            stage_started = time.perf_counter()

            conversation = (
                await self.conversation_service.get_or_create_conversation(
                    owner_id=owner.id,
                    platform=integration.platform,
                    external_conversation_id=(
                        incoming.external_conversation_id
                    ),
                    external_user_id=incoming.external_user_id,
                    external_user_name=incoming.external_user_name,
                )
            )

            inbound_message = await self.conversation_service.add_message(
                conversation,
                role=MessageRole.USER,
                content=incoming.text,
                message_type=incoming.message_type,
                external_message_id=incoming.external_message_id,
                media_file_id=incoming.media_file_id,
                latitude=incoming.latitude,
                longitude=incoming.longitude,
                platform_metadata=incoming.platform_metadata,
            )

            await self.db.commit()

            self._log_stage(
                "conversation_and_store_message",
                stage_started,
                conversation.id,
            )

            # ---------------------------------------------------------------
            # Read receipt / typing indicator
            # ---------------------------------------------------------------

            if (
                incoming.external_message_id
                and integration.settings.get("read_receipts", True)
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

            # ---------------------------------------------------------------
            # Customer
            # ---------------------------------------------------------------

            customer = None

            if incoming.external_user_id:
                stage_started = time.perf_counter()

                customer = (
                    await self.customer_service.get_or_create_customer(
                        owner_id=owner.id,
                        platform=integration.platform,
                        external_user_id=incoming.external_user_id,
                        display_name=incoming.external_user_name,
                    )
                )

                await self.db.commit()

                self._log_stage(
                    "customer_resolution",
                    stage_started,
                    conversation.id,
                )

            # ---------------------------------------------------------------
            # Human takeover / auto-reply guard
            # ---------------------------------------------------------------

            if (
                conversation.assigned_to_human
                or not integration.settings.get("auto_reply", True)
            ):
                return

            # ---------------------------------------------------------------
            # Business hours
            # ---------------------------------------------------------------

            after_hours_reply = _after_hours_reply(integration.settings)

            if after_hours_reply is not None:
                await self.conversation_service.add_message(
                    conversation,
                    role=MessageRole.SYSTEM,
                    content=after_hours_reply,
                )

                await self.db.commit()

                await adapter.send_text(
                    incoming.external_conversation_id,
                    after_hours_reply,
                )

                return

            # ---------------------------------------------------------------
            # Plan limit
            # ---------------------------------------------------------------

            stage_started = time.perf_counter()

            limit_reached, plan = await check_message_limit(
                self.db,
                owner.id,
            )

            self._log_stage(
                "plan_limit_check",
                stage_started,
                conversation.id,
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

            # ---------------------------------------------------------------
            # Normalize actual message content
            # ---------------------------------------------------------------

            effective_text = incoming.text

            # ---------------------------------------------------------------
            # IMAGE
            # ---------------------------------------------------------------

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

            # ---------------------------------------------------------------
            # VOICE
            # ---------------------------------------------------------------

            elif (
                incoming.message_type == MessageType.VOICE
                and incoming.media_file_id
            ):
                effective_text = await self._transcribe_voice(
                    incoming=incoming,
                    adapter=adapter,
                    inbound_message=inbound_message,
                )

            # ---------------------------------------------------------------
            # Agent + AI reply
            # ---------------------------------------------------------------

            try:
                stage_started = time.perf_counter()

                agent = await self._get_agent_for_conversation(
                    owner_id=owner.id,
                    conversation=conversation,
                    integration=integration,
                    effective_text=effective_text,
                )

                self._log_stage(
                    "agent_resolution",
                    stage_started,
                    conversation.id,
                )

                reply_text, top_product = await self._build_reply(
                    owner=owner,
                    conversation=conversation,
                    incoming=incoming,
                    inbound_message=inbound_message,
                    agent=agent,
                    customer=customer,
                    effective_text=effective_text,
                )

            except Exception:
                logger.error(
                    "Routing or reply generation failed for conversation %s",
                    conversation.id,
                    exc_info=True,
                )

                agent = None

                reply_text = (
                    "Sorry, something went wrong on our end. "
                    "We'll follow up shortly."
                )

                top_product = None

            # ---------------------------------------------------------------
            # Store outgoing message
            # ---------------------------------------------------------------

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=reply_text,
                agent_id=agent.id if agent is not None else None,
            )

            await self.db.commit()

            # ---------------------------------------------------------------
            # Product image
            # ---------------------------------------------------------------

            if top_product is not None and top_product.images:
                try:
                    caption = _build_product_photo_caption(
                        top_product
                    )

                    await adapter.send_photo(
                        incoming.external_conversation_id,
                        top_product.images[0],
                        caption,
                    )

                except Exception:
                    logger.warning(
                        "Failed to send product photo for product %s",
                        top_product.id,
                        exc_info=True,
                    )

            # ---------------------------------------------------------------
            # Text response
            # ---------------------------------------------------------------

            await adapter.send_text(
                incoming.external_conversation_id,
                reply_text,
            )

        finally:
            aclose = getattr(adapter, "aclose", None)

            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    logger.debug(
                        "Adapter close failed",
                        exc_info=True,
                    )

            elapsed_ms = (
                time.perf_counter() - pipeline_started
            ) * 1000

            logger.info(
                "Messaging pipeline completed in %.2f ms | platform=%s",
                elapsed_ms,
                integration.platform,
            )

    # -----------------------------------------------------------------------
    # Agent resolution
    # -----------------------------------------------------------------------

    async def _get_agent_for_conversation(
        self,
        owner_id: uuid.UUID,
        conversation: Conversation,
        integration: PlatformIntegration,
        effective_text: str | None,
    ) -> Agent:
        """
        Resolve the agent without repeatedly invoking Gemini.

        Priority:

        1. Existing conversation agent, if still active.
        2. Integration default agent, if configured and active.
        3. RouterService only when actual text exists.
        4. Deterministic first active agent for non-text messages.

        Once an agent is selected, it is persisted on the conversation.
        Subsequent messages therefore do not need to run Gemini routing.
        """

        # ---------------------------------------------------------------
        # 1. Existing conversation agent
        # ---------------------------------------------------------------

        if conversation.agent_id is not None:
            try:
                existing_agent = (
                    await self.router_service.agent_service.get_agent(
                        owner_id,
                        conversation.agent_id,
                    )
                )

                if existing_agent.status == AgentStatus.ACTIVE:
                    return existing_agent

            except HTTPException:
                logger.debug(
                    "Conversation agent %s is no longer available",
                    conversation.agent_id,
                )

        # ---------------------------------------------------------------
        # 2. Integration default agent
        # ---------------------------------------------------------------

        default_agent_id = integration.settings.get(
            "default_agent_id"
        )

        if default_agent_id:
            try:
                default_uuid = uuid.UUID(str(default_agent_id))

                default_agent = (
                    await self.router_service.agent_service.get_agent(
                        owner_id,
                        default_uuid,
                    )
                )

                if default_agent.status == AgentStatus.ACTIVE:
                    conversation.agent_id = default_agent.id

                    await self.db.commit()

                    return default_agent

            except (HTTPException, ValueError):
                logger.debug(
                    "Configured default agent %s is invalid or unavailable",
                    default_agent_id,
                )

        # ---------------------------------------------------------------
        # 3. AI router for actual text
        # ---------------------------------------------------------------

        if effective_text and effective_text.strip():
            agent = await self.router_service.route(
                owner_id,
                effective_text,
            )

        # ---------------------------------------------------------------
        # 4. Deterministic fallback for non-text
        # ---------------------------------------------------------------

        else:
            agent = await self._pick_agent_without_ai(
                owner_id,
                conversation,
                integration,
            )

        # Persist the selected agent so future messages in this conversation
        # don't invoke RouterService again.
        conversation.agent_id = agent.id

        await self.db.commit()

        return agent

    async def _pick_agent_without_ai(
        self,
        owner_id: uuid.UUID,
        conversation: Conversation,
        integration: PlatformIntegration,
    ) -> Agent:
        """
        Select an agent without an AI classification call.

        Used when there is no usable text to classify.
        """

        if conversation.agent_id is not None:
            try:
                agent = await self.router_service.agent_service.get_agent(
                    owner_id,
                    conversation.agent_id,
                )

                if agent.status == AgentStatus.ACTIVE:
                    return agent

            except HTTPException:
                pass

        default_agent_id = integration.settings.get(
            "default_agent_id"
        )

        if default_agent_id:
            try:
                default_agent = (
                    await self.router_service.agent_service.get_agent(
                        owner_id,
                        uuid.UUID(str(default_agent_id)),
                    )
                )

                if default_agent.status == AgentStatus.ACTIVE:
                    return default_agent

            except (HTTPException, ValueError):
                pass

        # Prefer an SQL-filtered active-agent method when available.
        list_active_agents = getattr(
            self.router_service.agent_service,
            "list_active_agents",
            None,
        )

        if list_active_agents is not None:
            active_agents = await list_active_agents(owner_id)
        else:
            # Backward-compatible fallback for the current AgentService.
            active_agents = [
                agent
                for agent in await self.router_service.agent_service.list_agents(
                    owner_id
                )
                if agent.status == AgentStatus.ACTIVE
            ]

        if not active_agents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=(
                    "This account has no active agents to handle messages."
                ),
            )

        return active_agents[0]

    # -----------------------------------------------------------------------
    # Message limit
    # -----------------------------------------------------------------------

    async def _handle_message_limit_reached(
        self,
        owner: User,
        integration: PlatformIntegration,
        conversation: Conversation,
        adapter,
        plan,
    ) -> None:
        """
        Send a deterministic limit message without invoking Gemini.

        The owner receives at most one notification within 24 hours.
        """

        reply_text = (
            "Thanks for your message! We've reached our messaging limit "
            "for this month — a team member will get back to you as soon "
            "as possible."
        )

        await self.conversation_service.add_message(
            conversation,
            role=MessageRole.SYSTEM,
            content=reply_text,
        )

        await self.db.commit()

        await adapter.send_text(
            conversation.external_conversation_id,
            reply_text,
        )

        recent_cutoff = (
            datetime.now(timezone.utc)
            - timedelta(hours=24)
        )

        already_notified = await self.db.execute(
            select(Notification.id).where(
                Notification.owner_id == owner.id,
                Notification.type == NotificationType.PLAN_LIMIT_REACHED,
                Notification.created_at >= recent_cutoff,
            )
        )

        if already_notified.scalar_one_or_none() is not None:
            return

        plan_name = (
            plan.name
            if plan is not None
            else "your plan"
        )

        if plan is not None:
            body = (
                f"{plan_name} allows "
                f"{plan.max_messages_per_month} messages/month, "
                f"and you've hit it. New messages are getting a "
                f"hold-tight reply instead of an AI response until "
                f"you upgrade or the month resets."
            )
        else:
            body = (
                "You've reached your plan's monthly message limit."
            )

        await NotificationService(self.db).create(
            owner_id=owner.id,
            type_=NotificationType.PLAN_LIMIT_REACHED,
            title="Monthly message limit reached",
            body=body,
            context={
                "integration_id": str(integration.id),
            },
        )

        await self.db.commit()

    # -----------------------------------------------------------------------
    # Image/payment handling
    # -----------------------------------------------------------------------

    async def _find_receipt_target_order(
        self,
        owner_id: uuid.UUID,
        customer_id: uuid.UUID,
    ) -> Order | None:
        """
        Find the newest order that is genuinely waiting for payment.

        A receipt is never attached to:
        - cancelled orders
        - refunded orders
        - delivered orders
        - already-paid orders
        """
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

    async def _handle_image_message(
        self,
        owner: User,
        conversation: Conversation,
        customer,
        incoming: IncomingMessage,
        adapter,
        inbound_message: Message,
    ) -> tuple[bool, str | None]:
        """
        Analyze an incoming image.

        Returns:

            (True, None)
                The method already sent the final reply.

            (False, effective_text)
                Continue through normal routing/RAG/generation.

        Payment screenshots are handled conservatively:
        the receipt is attached to the matching awaiting-payment order,
        but payment is NEVER automatically confirmed.
        """

        try:
            image_bytes, mime_type = await adapter.download_media(
                incoming.media_file_id
            )

            description = (
                await self.router_service.ai_provider.describe_image(
                    image_bytes,
                    mime_type,
                )
            )

        except Exception:
            logger.warning(
                "Image analysis failed for message %s in conversation %s",
                incoming.external_message_id,
                conversation.id,
                exc_info=True,
            )

            fallback = _NON_TEXT_ACKNOWLEDGEMENTS[
                MessageType.IMAGE
            ]

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=fallback,
            )

            await self.db.commit()

            await adapter.send_text(
                incoming.external_conversation_id,
                fallback,
            )

            return True, None

        caption_note = ""

        if incoming.text and incoming.text.strip():
            caption_note = (
                f' Caption: "{incoming.text.strip()}"'
            )

        enriched_text = (
            f"[Customer sent a photo.{caption_note} "
            f"What the photo shows: {description}]"
        )

        await self.conversation_service.update_message_content(
            inbound_message,
            enriched_text,
        )

        await self.db.commit()

        # ---------------------------------------------------------------
        # Payment receipt detection
        # ---------------------------------------------------------------

        if customer is not None:
            target_order = await self._find_receipt_target_order(
                owner.id,
                customer.id,
            )

            if target_order is not None:
                try:
                    classification = (
                        await self.router_service.ai_provider.classify(
                            description,
                            labels=[
                                (
                                    "payment_receipt_or_"
                                    "bank_transfer_confirmation"
                                ),
                                "something_else",
                            ],
                        )
                    )

                except Exception:
                    logger.warning(
                        "Payment receipt classification failed for "
                        "message %s",
                        incoming.external_message_id,
                        exc_info=True,
                    )

                    classification = "something_else"

                if (
                    classification
                    == "payment_receipt_or_bank_transfer_confirmation"
                ):
                    await self.order_service.attach_receipt(
                        owner.id,
                        target_order.id,
                        incoming.media_file_id,
                    )

                    reply_text = (
                        "Thanks — we've received your payment screenshot "
                        f"for order #{str(target_order.id)[:8].upper()}. "
                        "We'll review and confirm it shortly."
                    )

                    await self.conversation_service.add_message(
                        conversation,
                        role=MessageRole.AGENT,
                        content=reply_text,
                    )

                    await self.db.commit()

                    await adapter.send_text(
                        incoming.external_conversation_id,
                        reply_text,
                    )

                    return True, None

        return False, enriched_text

    # -----------------------------------------------------------------------
    # Voice handling
    # -----------------------------------------------------------------------

    async def _transcribe_voice(
        self,
        incoming: IncomingMessage,
        adapter,
        inbound_message: Message,
    ) -> str | None:
        """
        Download and transcribe a voice message.

        Returns the transcript or None if transcription failed.
        """

        try:
            audio_bytes, mime_type = await adapter.download_media(
                incoming.media_file_id
            )

            transcript = (
                await self.router_service.ai_provider.transcribe_audio(
                    audio_bytes,
                    mime_type,
                )
            )

        except Exception:
            logger.warning(
                "Voice transcription failed for message %s",
                incoming.external_message_id,
                exc_info=True,
            )

            return None

        transcript = (transcript or "").strip()

        if not transcript:
            return None

        await self.conversation_service.update_message_content(
            inbound_message,
            f"[Voice message transcript] {transcript}",
        )

        await self.db.commit()

        return transcript

    # -----------------------------------------------------------------------
    # Retrieval decision
    # -----------------------------------------------------------------------

    @classmethod
    def _needs_retrieval(cls, text: str) -> bool:
        """
        Decide whether semantic retrieval is worthwhile.

        This deliberately uses a conservative exact-match list rather than
        message length. Short questions such as "price?" or "where are you?"
        can still require knowledge/product context.
        """

        normalized = " ".join(
            (text or "").lower().split()
        ).strip()

        if not normalized:
            return False

        return normalized not in cls._SIMPLE_MESSAGES

    # -----------------------------------------------------------------------
    # Tool decision
    # -----------------------------------------------------------------------

    @classmethod
    def _needs_tools(cls, text: str) -> bool:
        """
        Decide whether the expensive Gemini tool-calling loop is justified.

        Ordinary conversation and product-information questions can use the
        normal generate() path.

        Tool calling is reserved for customer/account/order/payment actions.
        """

        normalized = " ".join(
            (text or "").lower().split()
        ).strip()

        if not normalized:
            return False

        return any(
            phrase in normalized
            for phrase in cls._TOOL_PHRASES
        )

    # -----------------------------------------------------------------------
    # Reply generation
    # -----------------------------------------------------------------------

    async def _build_reply(
        self,
        owner: User,
        conversation: Conversation,
        incoming: IncomingMessage,
        inbound_message: Message,
        agent: Agent,
        customer,
        effective_text: str | None,
    ) -> tuple[str, Product | None]:
        """
        Build and generate the response.

        Performance-critical sequence:

            one query embedding
                    |
                    +--> knowledge
                    +--> memory
                    +--> products
                    |
                    +--> prompt
                    |
                    +--> generate / generate_with_tools

        No retrieval embedding is performed when the message is trivial.
        """

        if not effective_text or not effective_text.strip():
            return (
                _NON_TEXT_ACKNOWLEDGEMENTS.get(
                    incoming.message_type,
                    "Got it, thanks!",
                ),
                None,
            )

        effective_text = effective_text.strip()

        retrieval_needed = self._needs_retrieval(
            effective_text
        )

        knowledge_results = []
        memory_results = []
        product_results = []

        # ---------------------------------------------------------------
        # One embedding for all semantic retrieval
        # ---------------------------------------------------------------

        if retrieval_needed:
            embedding_started = time.perf_counter()

            query_vector = (
                await self.router_service.ai_provider.embed(
                    [effective_text]
                )
            )[0]

            self._log_stage(
                "query_embedding",
                embedding_started,
                conversation.id,
            )

            # IMPORTANT:
            # These searches intentionally remain sequential because all
            # services share the same AsyncSession. AsyncSession should not
            # be concurrently used through asyncio.gather().
            retrieval_started = time.perf_counter()

            knowledge_results = (
                await self.knowledge_service.search(
                    owner.id,
                    query_vector,
                    agent_id=agent.id,
                    top_k=3,
                )
            )

            self._log_stage(
                "knowledge_search",
                retrieval_started,
                conversation.id,
            )

            retrieval_started = time.perf_counter()

            memory_results = (
                await self.memory_service.search(
                    owner.id,
                    query_vector,
                    agent_id=agent.id,
                    top_k=3,
                )
            )

            self._log_stage(
                "memory_search",
                retrieval_started,
                conversation.id,
            )

            retrieval_started = time.perf_counter()

            product_results = (
                await self.product_service.search(
                    owner.id,
                    query_vector,
                    top_k=3,
                )
            )

            self._log_stage(
                "product_search",
                retrieval_started,
                conversation.id,
            )

        # ---------------------------------------------------------------
        # Recent conversation history
        # ---------------------------------------------------------------

        history_started = time.perf_counter()

        history = (
            await self.conversation_service.get_recent_messages(
                conversation.id,
                limit=self.HISTORY_LIMIT,
            )
        )

        self._log_stage(
            "conversation_history",
            history_started,
            conversation.id,
        )

        # ---------------------------------------------------------------
        # Prompt
        # ---------------------------------------------------------------

        system_instruction = self._build_system_instruction(
            agent=agent,
            knowledge_results=knowledge_results,
            memory_results=memory_results,
            product_results=product_results,
        )

        prompt = self._build_prompt(
            history=history,
            latest_text=effective_text,
            current_message_id=inbound_message.id,
        )

        # ---------------------------------------------------------------
        # Generation
        # ---------------------------------------------------------------

        generation_started = time.perf_counter()

        use_tools = (
            customer is not None
            and self._needs_tools(effective_text)
        )

        if use_tools:
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

            generation_mode = "tools"

        else:
            reply_text = (
                await self.router_service.ai_provider.generate(
                    prompt,
                    system_instruction=system_instruction,
                    temperature=agent.temperature,
                )
            )

            generation_mode = "standard"

        self._log_stage(
            f"generation_{generation_mode}",
            generation_started,
            conversation.id,
        )

        # ---------------------------------------------------------------
        # Product image selection
        # ---------------------------------------------------------------

        top_product = None

        if product_results:
            best_product, best_score = product_results[0]

            if best_score >= PRODUCT_PHOTO_MIN_SCORE:
                top_product = best_product

        return reply_text, top_product

    # -----------------------------------------------------------------------
    # System prompt
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_system_instruction(
        agent,
        knowledge_results,
        memory_results,
        product_results,
    ) -> str:
        """
        Build the system instruction from the selected context.

        Only retrieved context is included; the complete knowledge base,
        memory table, or product catalogue is never dumped into the prompt.
        """

        parts = [
            agent.instructions,
        ]

        if knowledge_results:
            knowledge_lines = "\n".join(
                f"- {chunk.content}"
                for chunk, _score in knowledge_results
            )

            parts.append(
                "Relevant knowledge base entries:\n"
                f"{knowledge_lines}"
            )

        if memory_results:
            memory_lines = "\n".join(
                f"- {entry.content}"
                for entry, _score in memory_results
            )

            parts.append(
                "Relevant things you know/remember:\n"
                f"{memory_lines}"
            )

        if product_results:
            product_lines = "\n".join(
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
                for product, _score in product_results
            )

            parts.append(
                "Relevant products/services you can sell:\n"
                f"{product_lines}"
            )

        return "\n\n".join(
            part
            for part in parts
            if part
        )

    # -----------------------------------------------------------------------
    # Prompt
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        history: list[Message],
        latest_text: str,
        current_message_id: uuid.UUID | None = None,
    ) -> str:
        """
        Build the conversational prompt without duplicating the current
        inbound message.

        The current message has already been persisted before this method is
        called. Therefore get_recent_messages() can contain it. We explicitly
        exclude it by primary key rather than comparing message text, because
        comparing text is ambiguous when a customer repeats themselves.
        """

        lines: list[str] = []

        for message in history:
            if (
                current_message_id is not None
                and message.id == current_message_id
            ):
                continue

            if message.role == MessageRole.USER:
                lines.append(
                    f"Customer: {message.content or ''}"
                )

            elif message.role == MessageRole.AGENT:
                lines.append(
                    f"You: {message.content or ''}"
                )

        lines.append(
            f"Customer: {latest_text}"
        )

        lines.append("You:")

        return "\n".join(lines)

    # -----------------------------------------------------------------------
    # Performance logging
    # -----------------------------------------------------------------------

    @staticmethod
    def _log_stage(
        stage: str,
        started: float,
        context_id,
    ) -> None:
        """
        Emit a compact stage timing log.

        These measurements are intentionally kept in the pipeline so a
        production log can immediately show whether latency comes from:
        database work, embeddings, retrieval, routing, generation, or
        another stage.
        """

        elapsed_ms = (
            time.perf_counter() - started
        ) * 1000

        logger.info(
            "MessagingPipeline stage=%s elapsed_ms=%.2f context=%s",
            stage,
            elapsed_ms,
            context_id,
        )

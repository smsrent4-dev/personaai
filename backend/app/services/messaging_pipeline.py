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
 14. Optionally send a relevant product image.

Important production behavior:

- Gemini/provider retries are handled by the AI provider.
- This pipeline does NOT retry the entire message because doing so could
  duplicate side effects such as orders, receipts or other tools.
- Routing failure and response-generation failure are logged separately.
- If AI routing fails, the pipeline falls back to an already-known/default
  agent where possible instead of unnecessarily abandoning the conversation.
"""

import logging
from datetime import datetime
from typing import Any

from fastapi import HTTPException
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
from app.services.tools import ToolContext, default_tool_definitions, execute_tool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Order/payment constants
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
# Product matching
# ---------------------------------------------------------------------------

PRODUCT_PHOTO_MIN_SCORE = 0.5


def _build_product_photo_caption(product: Product) -> str:
    """Build a useful caption for a product image.

    The caption contains:
      - product name
      - price/currency
      - available variants
      - inventory state
      - short description
    """

    lines = [
        f"{product.name} — {product.price} {product.currency}"
    ]

    variants = product.variants or []

    variant_names = [
        variant.get("name")
        for variant in variants
        if isinstance(variant, dict) and variant.get("name")
    ]

    if variant_names:
        lines.append(f"Available: {', '.join(variant_names)}")

    if product.inventory is not None:
        if product.inventory > 0:
            lines.append("In stock")
        else:
            lines.append("Currently out of stock")

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
    """Return an after-hours message when business hours are configured."""

    business_hours = settings.get("business_hours")

    if not business_hours or not business_hours.get("enabled"):
        return None

    try:
        import zoneinfo

        timezone_name = business_hours.get("timezone", "UTC")
        timezone = zoneinfo.ZoneInfo(timezone_name)

        now = datetime.now(timezone)
        today_key = _WEEKDAY_KEYS[now.weekday()]

        window = (
            business_hours
            .get("hours", {})
            .get(today_key)
        )

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
            "Malformed business_hours settings; ignoring business-hours rule",
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
# MessagingPipeline
# ===========================================================================


class MessagingPipeline:
    """Orchestrates inbound platform messages."""

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
    # Main entry point
    # -----------------------------------------------------------------------

    async def handle_incoming(
        self,
        owner: User,
        integration: PlatformIntegration,
        raw_payload: dict,
    ) -> None:
        """Process one incoming platform webhook/message."""

        adapter = build_adapter(integration)

        try:
            # ---------------------------------------------------------------
            # 1. Parse incoming platform payload
            # ---------------------------------------------------------------

            incoming = adapter.parse_incoming(raw_payload)

            if incoming is None:
                logger.debug(
                    "Platform adapter ignored incoming payload for integration %s",
                    integration.id,
                )
                return

            logger.info(
                (
                    "Processing incoming message: platform=%s "
                    "conversation=%s message_type=%s external_message_id=%s"
                ),
                integration.platform,
                incoming.external_conversation_id,
                incoming.message_type,
                incoming.external_message_id,
            )

            # ---------------------------------------------------------------
            # 2. Get/create conversation
            # ---------------------------------------------------------------

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

            # ---------------------------------------------------------------
            # 3. Store inbound message
            # ---------------------------------------------------------------

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

            # ---------------------------------------------------------------
            # 4. Mark platform message as read / typing
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
            # 5. Get/create customer
            # ---------------------------------------------------------------

            customer = None

            if incoming.external_user_id:
                customer = (
                    await self.customer_service.get_or_create_customer(
                        owner_id=owner.id,
                        platform=integration.platform,
                        external_user_id=incoming.external_user_id,
                        display_name=incoming.external_user_name,
                    )
                )

                await self.db.commit()

            # ---------------------------------------------------------------
            # 6. Human takeover / auto-reply disabled
            # ---------------------------------------------------------------

            if conversation.assigned_to_human:
                logger.info(
                    "Skipping AI reply because conversation %s is assigned "
                    "to a human",
                    conversation.id,
                )
                return

            if not integration.settings.get("auto_reply", True):
                logger.info(
                    "Skipping AI reply because auto_reply is disabled "
                    "for integration %s",
                    integration.id,
                )
                return

            # ---------------------------------------------------------------
            # 7. Business-hours rule
            # ---------------------------------------------------------------

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

                await adapter.send_text(
                    incoming.external_conversation_id,
                    after_hours_reply,
                )

                return

            # ---------------------------------------------------------------
            # 8. Plan message limit
            # ---------------------------------------------------------------

            limit_reached, plan = await check_message_limit(
                self.db,
                owner.id,
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
            # 9. Convert image/voice into useful text
            # ---------------------------------------------------------------

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
                effective_text = await self._transcribe_voice(
                    incoming=incoming,
                    adapter=adapter,
                    inbound_message=inbound_message,
                )

            # ---------------------------------------------------------------
            # 10. Select agent
            #
            # IMPORTANT:
            # Routing failure is handled separately from response failure.
            # If AI routing is temporarily unavailable, we still try to use
            # the conversation/default/first active agent.
            # ---------------------------------------------------------------

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
                        "AI routing selected agent %s for conversation %s",
                        getattr(agent, "id", None),
                        conversation.id,
                    )

                except Exception:
                    logger.error(
                        (
                            "AI routing failed for conversation %s; "
                            "falling back to a deterministic agent"
                        ),
                        conversation.id,
                        exc_info=True,
                    )

                    try:
                        agent = await self._pick_agent_without_ai(
                            owner.id,
                            conversation,
                            integration,
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
                    agent = await self._pick_agent_without_ai(
                        owner.id,
                        conversation,
                        integration,
                    )
                except Exception:
                    logger.error(
                        "Unable to select an agent for conversation %s",
                        conversation.id,
                        exc_info=True,
                    )
                    agent = None

            # ---------------------------------------------------------------
            # 11. Generate response
            # ---------------------------------------------------------------

            if agent is None:
                reply_text = (
                    "Sorry, we're unable to respond right now. "
                    "A team member will follow up shortly."
                )
                top_product = None

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

                    reply_text, top_product = await self._build_reply(
                        owner=owner,
                        conversation=conversation,
                        incoming=incoming,
                        inbound_message=inbound_message,
                        agent=agent,
                        customer=customer,
                        effective_text=effective_text,
                    )

                    logger.info(
                        "AI reply generated successfully for conversation %s",
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

            # ---------------------------------------------------------------
            # 12. Store outgoing message
            # ---------------------------------------------------------------

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=reply_text,
                agent_id=agent.id if agent is not None else None,
            )

            await self.db.commit()

            # ---------------------------------------------------------------
            # 13. Optional product image
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
            # 14. Send final text response
            # ---------------------------------------------------------------

            await adapter.send_text(
                incoming.external_conversation_id,
                reply_text,
            )

            logger.info(
                "Incoming message processing completed: conversation=%s",
                conversation.id,
            )

        except Exception:
            # This is intentionally only the final safety net.
            #
            # We do not retry the whole pipeline here because a retry could
            # repeat side effects such as:
            #   - creating orders
            #   - attaching receipts
            #   - executing customer tools
            #   - sending duplicate platform messages
            #
            logger.error(
                "Unhandled messaging pipeline error for integration %s",
                integration.id,
                exc_info=True,
            )

            raise

        finally:
            aclose = getattr(adapter, "aclose", None)

            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    logger.debug(
                        "Platform adapter close failed",
                        exc_info=True,
                    )

    # -----------------------------------------------------------------------
    # Plan limit
    # -----------------------------------------------------------------------

    async def _handle_message_limit_reached(
        self,
        owner: User,
        integration: PlatformIntegration,
        conversation: Conversation,
        adapter: Any,
        plan: Any,
    ) -> None:
        """Send a plan-limit response and notify the owner once per day."""

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
                "Failed to send plan-limit message for conversation %s",
                conversation.id,
                exc_info=True,
            )

        # ---------------------------------------------------------------
        # Notify owner only once per 24 hours.
        # ---------------------------------------------------------------

        try:
            since = datetime.now().astimezone() - __import__(
                "datetime"
            ).timedelta(hours=24)

            existing_notification = await self.db.scalar(
                select(Notification)
                .where(
                    Notification.owner_id == owner.id,
                    Notification.type == NotificationType.PLAN_LIMIT_REACHED,
                    Notification.created_at >= since,
                )
                .order_by(Notification.created_at.desc())
            )

            if existing_notification is None:
                notification_service = NotificationService(self.db)

                await notification_service.create_notification(
                    owner_id=owner.id,
                    notification_type=NotificationType.PLAN_LIMIT_REACHED,
                    title="Monthly messaging limit reached",
                    message=(
                        "Your monthly messaging limit has been reached. "
                        "Customers can still be handled manually."
                    ),
                )

                await self.db.commit()

        except Exception:
            logger.warning(
                "Failed to create plan-limit notification for owner %s",
                owner.id,
                exc_info=True,
            )

    # -----------------------------------------------------------------------
    # Receipt order lookup
    # -----------------------------------------------------------------------

    async def _find_receipt_target_order(
        self,
        owner_id,
        customer_id,
    ):
        """Find the customer's newest order that is awaiting payment.

        We deliberately do not auto-confirm payment. A receipt image can
        be attached to the relevant order, but final payment confirmation
        remains a business-side decision.
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

    # -----------------------------------------------------------------------
    # Image handling
    # -----------------------------------------------------------------------

    async def _handle_image_message(
        self,
        owner: User,
        conversation: Conversation,
        customer,
        incoming,
        adapter,
        inbound_message: Message,
    ) -> tuple[bool, str | None]:
        """Download and understand an incoming image.

        Payment screenshots/receipts receive special handling:

        1. Vision describes the image.
        2. If it appears to be a payment confirmation, we locate the
           customer's newest order awaiting payment.
        3. The image is attached as a receipt where supported.
        4. Payment is NOT automatically confirmed.

        This prevents the AI from treating a screenshot as proof that
        money has actually settled.
        """

        if not incoming.media_file_id:
            return False, incoming.text

        try:
            logger.info(
                "Downloading image for conversation %s",
                conversation.id,
            )

            image_data = await adapter.download_media(
                incoming.media_file_id
            )

            if not image_data:
                raise ValueError("Platform returned empty image data")

            logger.info(
                "Analyzing image for conversation %s",
                conversation.id,
            )

            description = (
                await self.router_service.ai_provider.describe_image(
                    image_data
                )
            )

            description = (description or "").strip()

            if not description:
                raise ValueError(
                    "Image analysis returned empty description"
                )

            # -----------------------------------------------------------
            # Save useful image understanding onto the original message.
            # -----------------------------------------------------------

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

            inbound_message.content = effective_text

            await self.db.commit()

            # -----------------------------------------------------------
            # Payment receipt detection.
            #
            # We use a second lightweight AI classification here because
            # image description alone is not guaranteed to distinguish
            # a receipt from a normal product/photo image.
            # -----------------------------------------------------------

            if customer is not None:
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
                        .replace(" ", "_")
                        .replace("-", "_")
                    )

                    is_payment_receipt = (
                        "payment_receipt" in normalized_classification
                        or "bank_transfer" in normalized_classification
                        or normalized_classification
                        == "payment_receipt_or_bank_transfer_confirmation"
                    )

                except Exception:
                    logger.warning(
                        (
                            "Image classification failed for conversation "
                            "%s; treating image as a normal image"
                        ),
                        conversation.id,
                        exc_info=True,
                    )

                    is_payment_receipt = False

                if is_payment_receipt:
                    order = await self._find_receipt_target_order(
                        owner.id,
                        customer.id,
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

                            await adapter.send_text(
                                incoming.external_conversation_id,
                                confirmation,
                            )

                            logger.info(
                                (
                                    "Payment receipt attached to order %s "
                                    "for conversation %s"
                                ),
                                order.id,
                                conversation.id,
                            )

                            return True, effective_text

                        except Exception:
                            logger.error(
                                (
                                    "Failed to attach payment receipt for "
                                    "order %s"
                                ),
                                order.id,
                                exc_info=True,
                            )

            return False, effective_text

        except Exception:
            logger.error(
                "Image processing failed for conversation %s",
                conversation.id,
                exc_info=True,
            )

            fallback = _NON_TEXT_ACKNOWLEDGEMENTS.get(
                MessageType.IMAGE,
                "Thanks for the image - I've received it.",
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
                    "Failed to send image fallback acknowledgement",
                    exc_info=True,
                )

            return True, None

    # -----------------------------------------------------------------------
    # Voice handling
    # -----------------------------------------------------------------------

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

            audio_data = await adapter.download_media(
                incoming.media_file_id
            )

            if not audio_data:
                raise ValueError("Platform returned empty audio data")

            transcript = (
                await self.router_service.ai_provider.transcribe_audio(
                    audio_data
                )
            )

            transcript = (transcript or "").strip()

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

            return incoming.text

    # -----------------------------------------------------------------------
    # Deterministic agent selection
    # -----------------------------------------------------------------------

    async def _pick_agent_without_ai(
        self,
        owner_id,
        conversation: Conversation,
        integration: PlatformIntegration,
    ) -> Agent:
        """Select an agent without calling Gemini.

        Priority:

        1. Existing conversation agent.
        2. Integration default agent.
        3. First active owner agent.
        """

        # ---------------------------------------------------------------
        # Existing conversation assignment
        # ---------------------------------------------------------------

        if conversation.agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == conversation.agent_id,
                    Agent.owner_id == owner_id,
                )
            )

            agent = result.scalar_one_or_none()

            if agent is not None:
                return agent

        # ---------------------------------------------------------------
        # Integration default agent
        # ---------------------------------------------------------------

        default_agent_id = integration.default_agent_id

        if default_agent_id:
            result = await self.db.execute(
                select(Agent).where(
                    Agent.id == default_agent_id,
                    Agent.owner_id == owner_id,
                )
            )

            agent = result.scalar_one_or_none()

            if agent is not None:
                return agent

        # ---------------------------------------------------------------
        # First active agent
        # ---------------------------------------------------------------

        result = await self.db.execute(
            select(Agent)
            .where(
                Agent.owner_id == owner_id,
                Agent.status == AgentStatus.ACTIVE,
            )
            .order_by(Agent.created_at.asc())
        )

        agent = result.scalars().first()

        if agent is not None:
            return agent

        raise HTTPException(
            status_code=404,
            detail="No active AI agent is available for this account.",
        )

    # -----------------------------------------------------------------------
    # Build AI response
    # -----------------------------------------------------------------------

    async def _build_reply(
        self,
        owner: User,
        conversation: Conversation,
        incoming,
        inbound_message: Message,
        agent: Agent,
        customer,
        effective_text: str | None,
    ) -> tuple[str, Product | None]:
        """Build context and generate the AI reply."""

        # ---------------------------------------------------------------
        # No usable text.
        # ---------------------------------------------------------------

        if not effective_text:
            return (
                _NON_TEXT_ACKNOWLEDGEMENTS.get(
                    incoming.message_type,
                    "Got it, thanks!",
                ),
                None,
            )

        # ---------------------------------------------------------------
        # RAG: knowledge
        # ---------------------------------------------------------------

        knowledge_results = await self.knowledge_service.search(
            owner.id,
            effective_text,
            agent_id=agent.id,
            top_k=3,
        )

        # ---------------------------------------------------------------
        # RAG: memory
        # ---------------------------------------------------------------

        memory_results = await self.memory_service.search(
            owner.id,
            effective_text,
            agent_id=agent.id,
            top_k=3,
        )

        # ---------------------------------------------------------------
        # Product search
        # ---------------------------------------------------------------

        product_results = await self.product_service.search(
            owner.id,
            effective_text,
            top_k=3,
        )

        # ---------------------------------------------------------------
        # Conversation history
        #
        # We intentionally retrieve one extra message because the current
        # inbound message has already been stored in the database.
        # _build_prompt() then excludes that exact message by ID.
        # ---------------------------------------------------------------

        history = await self.conversation_service.get_recent_messages(
            conversation.id,
            limit=11,
        )

        # ---------------------------------------------------------------
        # Build system instruction
        # ---------------------------------------------------------------

        system_instruction = self._build_system_instruction(
            agent=agent,
            knowledge_results=knowledge_results,
            memory_results=memory_results,
            product_results=product_results,
        )

        # ---------------------------------------------------------------
        # Build conversation prompt.
        #
        # IMPORTANT:
        # inbound_message.id is passed so the current message is not added
        # twice:
        #
        # history:
        #   Customer: Hello
        #   You: Hi
        #   Customer: What is the price?
        #
        # latest_text:
        #   What is the price?
        #
        # Before this fix the prompt could become:
        #
        #   Customer: What is the price?
        #   Customer: What is the price?
        # ---------------------------------------------------------------

        prompt = self._build_prompt(
            history=history,
            latest_text=effective_text,
            current_message_id=inbound_message.id,
        )

        # ---------------------------------------------------------------
        # Customer-aware tool calling
        # ---------------------------------------------------------------

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
            reply_text = await self.router_service.ai_provider.generate(
                prompt,
                system_instruction=system_instruction,
                temperature=agent.temperature,
            )

        # ---------------------------------------------------------------
        # Product image decision
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
        """Build the system instruction supplied to the AI model."""

        parts = [
            agent.instructions,
        ]

        # ---------------------------------------------------------------
        # Knowledge
        # ---------------------------------------------------------------

        if knowledge_results:
            knowledge_lines = "\n".join(
                f"- {chunk.content}"
                for chunk, _score in knowledge_results
            )

            parts.append(
                "Relevant knowledge base entries:\n"
                f"{knowledge_lines}"
            )

        # ---------------------------------------------------------------
        # Memory
        # ---------------------------------------------------------------

        if memory_results:
            memory_lines = "\n".join(
                f"- {entry.content}"
                for entry, _score in memory_results
            )

            parts.append(
                "Relevant things you know/remember:\n"
                f"{memory_lines}"
            )

        # ---------------------------------------------------------------
        # Products
        # ---------------------------------------------------------------

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
    # Conversation prompt
    # -----------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        history: list[Message],
        latest_text: str,
        current_message_id=None,
    ) -> str:
        """Build the conversation prompt without duplicating the latest turn.

        The current incoming message is already persisted before this method
        is called. Therefore, when it exists in `history`, it must be skipped.

        We identify it by database ID rather than matching text because a
        customer can legitimately send the exact same text more than once.
        """

        lines: list[str] = []

        for message in history:
            # -----------------------------------------------------------
            # Do not include the current inbound message twice.
            # -----------------------------------------------------------

            if (
                current_message_id is not None
                and message.id == current_message_id
            ):
                continue

            if message.role == MessageRole.USER:
                if message.content:
                    lines.append(
                        f"Customer: {message.content}"
                    )

            elif message.role == MessageRole.AGENT:
                if message.content:
                    lines.append(
                        f"You: {message.content}"
                    )

        # ---------------------------------------------------------------
        # Always add the current user turn exactly once.
        # ---------------------------------------------------------------

        if latest_text:
            lines.append(
                f"Customer: {latest_text}"
            )

        lines.append("You:")

        return "\n".join(lines)

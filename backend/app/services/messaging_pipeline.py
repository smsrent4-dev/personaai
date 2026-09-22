"""MessagingPipeline — orchestrates incoming platform messages end-to-end.

Flow for handle_incoming():

    1. Parse platform payload into IncomingMessage.
    2. Resolve/create the conversation.
    3. Persist the inbound message.
    4. Handle media:
       - IMAGE -> download, vision analysis, optional receipt detection.
       - VOICE -> download and transcription.
    5. Route the message to the appropriate agent.
    6. Retrieve knowledge, memory, and product context.
    7. Generate the response through the AIProvider abstraction.
    8. Persist the outbound message.
    9. Optionally send a relevant product image.
   10. Send the generated text through the platform adapter.

This module is orchestration only. Provider-specific behavior belongs in
AIProvider implementations such as GeminiProvider.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

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
from app.services.tools import (
    ToolContext,
    default_tool_definitions,
    execute_tool,
)

logger = logging.getLogger(__name__)


_AWAITING_PAYMENT_STATUSES = {
    PaymentStatus.UNPAID,
    PaymentStatus.AWAITING_CONFIRMATION,
}

_CLOSED_ORDER_STATUSES = {
    OrderStatus.CANCELLED,
    OrderStatus.REFUNDED,
    OrderStatus.DELIVERED,
}

PRODUCT_PHOTO_MIN_SCORE = 0.5

PAYMENT_RECEIPT_LABEL = "payment_receipt_or_bank_transfer_confirmation"
NON_PAYMENT_IMAGE_LABEL = "something_else"

IMAGE_ANALYSIS_FAILURE_REPLY = (
    "I received your image, but I'm temporarily unable to analyze images "
    "right now. Please try again shortly."
)

VOICE_TRANSCRIPTION_FAILURE_REPLY = (
    "I received your voice message, but I'm temporarily unable to process "
    "voice messages right now. Please try again shortly, or send your "
    "message as text."
)

GENERAL_PROCESSING_FAILURE_REPLY = (
    "Sorry, something went wrong while processing your message. "
    "We'll follow up shortly."
)

_PAYMENT_RECEIPT_REPLY_TEMPLATE = (
    "Thanks — we've received your payment screenshot for order #{order_id}. "
    "We'll review and confirm it shortly."
)

_WEEKDAY_KEYS = [
    "mon",
    "tue",
    "wed",
    "thu",
    "fri",
    "sat",
    "sun",
]


def _build_product_photo_caption(product: Product) -> str:
    """Build a useful caption for a product image."""

    lines = [
        f"{product.name} — {product.price} {product.currency}",
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
        lines.append(
            "In stock"
            if product.inventory > 0
            else "Currently out of stock"
        )

    if product.description:
        lines.append(product.description[:200])

    return "\n".join(lines)[:1024]


_NON_TEXT_ACKNOWLEDGEMENTS = {
    MessageType.DOCUMENT: (
        "Thanks for the document — I've received it and will follow up shortly."
    ),
    MessageType.LOCATION: "Thanks for sharing your location — noted.",
    MessageType.VIDEO: (
        "Thanks for the video — I've received it and will follow up shortly."
    ),
    MessageType.CONTACT: "Thanks for sharing that contact — noted.",
    MessageType.OTHER: "Got it, thanks!",
}


def _after_hours_reply(settings: dict[str, Any]) -> str | None:
    """Return an after-hours response when business hours are configured.

    Invalid business-hour configuration fails open and allows normal
    message processing.
    """

    business_hours = settings.get("business_hours")

    if not business_hours or not business_hours.get("enabled"):
        return None

    try:
        from datetime import datetime as _datetime
        import zoneinfo

        timezone_name = business_hours.get("timezone", "UTC")
        timezone_info = zoneinfo.ZoneInfo(timezone_name)

        now = _datetime.now(timezone_info)
        weekday = _WEEKDAY_KEYS[now.weekday()]

        window = business_hours.get("hours", {}).get(weekday)

        if not window:
            is_open = False
        else:
            if not isinstance(window, (list, tuple)) or len(window) != 2:
                raise ValueError("Business-hour window must contain open/close.")

            open_str, close_str = window

            open_time = _datetime.strptime(
                open_str,
                "%H:%M",
            ).time()

            close_time = _datetime.strptime(
                close_str,
                "%H:%M",
            ).time()

            is_open = open_time <= now.time() <= close_time

    except Exception:
        logger.warning(
            "Malformed business_hours configuration; failing open.",
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
    """Orchestrates platform messages through PersonaAI services."""

    def __init__(self, db: AsyncSession):
        self.db = db

        self.conversation_service = ConversationService(db)
        self.router_service = RouterService(db)
        self.knowledge_service = KnowledgeService(db)
        self.memory_service = MemoryService(db)
        self.product_service = ProductService(db)
        self.customer_service = CustomerService(db)
        self.order_service = OrderService(db)

    async def handle_incoming(
        self,
        owner: User,
        integration: PlatformIntegration,
        raw_payload: dict,
    ) -> None:
        """Process one incoming platform payload.

        All platform-specific transport behavior remains inside the adapter.
        All model/provider-specific behavior remains behind AIProvider.
        """

        adapter = build_adapter(integration)

        try:
            incoming = adapter.parse_incoming(raw_payload)

            if incoming is None:
                return

            conversation = (
                await self.conversation_service.get_or_create_conversation(
                    owner_id=owner.id,
                    platform=integration.platform,
                    external_conversation_id=incoming.external_conversation_id,
                    external_user_id=incoming.external_user_id,
                    external_user_name=incoming.external_user_name,
                )
            )

            inbound_message = (
                await self.conversation_service.add_message(
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
            )

            await self.db.commit()

            await self._mark_message_read(
                adapter=adapter,
                incoming=incoming,
                integration=integration,
            )

            customer = await self._resolve_customer(
                owner=owner,
                integration=integration,
                incoming=incoming,
            )

            if conversation.assigned_to_human:
                return

            if not integration.settings.get("auto_reply", True):
                return

            after_hours_reply = _after_hours_reply(integration.settings)

            if after_hours_reply is not None:
                await self._send_stored_reply(
                    conversation=conversation,
                    external_conversation_id=(
                        incoming.external_conversation_id
                    ),
                    adapter=adapter,
                    content=after_hours_reply,
                    role=MessageRole.SYSTEM,
                )
                return

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

                if not effective_text:
                    await self._send_media_processing_failure(
                        conversation=conversation,
                        external_conversation_id=(
                            incoming.external_conversation_id
                        ),
                        adapter=adapter,
                        content=VOICE_TRANSCRIPTION_FAILURE_REPLY,
                    )
                    return

            try:
                agent = await self._resolve_agent(
                    owner=owner,
                    conversation=conversation,
                    integration=integration,
                    effective_text=effective_text,
                )

                reply_text, top_product = await self._build_reply(
                    owner=owner,
                    conversation=conversation,
                    incoming=incoming,
                    agent=agent,
                    customer=customer,
                    effective_text=effective_text,
                )

            except Exception:
                logger.error(
                    (
                        "Routing or reply generation failed for "
                        "conversation %s"
                    ),
                    conversation.id,
                    exc_info=True,
                )

                agent = None
                reply_text = GENERAL_PROCESSING_FAILURE_REPLY
                top_product = None

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=reply_text,
                agent_id=agent.id if agent is not None else None,
            )

            await self.db.commit()

            await self._send_product_photo(
                adapter=adapter,
                incoming=incoming,
                product=top_product,
            )

            await adapter.send_text(
                incoming.external_conversation_id,
                reply_text,
            )

        except Exception:
            logger.error(
                (
                    "Unhandled messaging pipeline failure for "
                    "integration %s"
                ),
                integration.id,
                exc_info=True,
            )

        finally:
            aclose = getattr(adapter, "aclose", None)

            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    logger.warning(
                        "Failed to close platform adapter.",
                        exc_info=True,
                    )

    async def _mark_message_read(
        self,
        adapter,
        incoming: IncomingMessage,
        integration: PlatformIntegration,
    ) -> None:
        """Mark an inbound message read and optionally show typing."""

        if not incoming.external_message_id:
            return

        if not integration.settings.get("read_receipts", True):
            return

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
                "Failed to mark message %s as read.",
                incoming.external_message_id,
                exc_info=True,
            )

    async def _resolve_customer(
        self,
        owner: User,
        integration: PlatformIntegration,
        incoming: IncomingMessage,
    ):
        """Resolve the PersonaAI customer associated with the sender."""

        if not incoming.external_user_id:
            return None

        try:
            customer = (
                await self.customer_service.get_or_create_customer(
                    owner_id=owner.id,
                    platform=integration.platform,
                    external_user_id=incoming.external_user_id,
                    display_name=incoming.external_user_name,
                )
            )

            await self.db.commit()
            return customer

        except Exception:
            await self.db.rollback()

            logger.error(
                (
                    "Failed to resolve customer for external user %s "
                    "on integration %s"
                ),
                incoming.external_user_id,
                integration.id,
                exc_info=True,
            )

            return None

    async def _handle_message_limit_reached(
        self,
        owner: User,
        integration: PlatformIntegration,
        conversation: Conversation,
        adapter,
        plan,
    ) -> None:
        """Send a non-AI response after the monthly plan limit is reached."""

        reply_text = (
            "Thanks for your message! We've reached our messaging limit "
            "for this month — a team member will get back to you as soon "
            "as possible."
        )

        await self._send_stored_reply(
            conversation=conversation,
            external_conversation_id=conversation.external_conversation_id,
            adapter=adapter,
            content=reply_text,
            role=MessageRole.SYSTEM,
        )

        recent_cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=24)
        )

        result = await self.db.execute(
            select(Notification.id).where(
                Notification.owner_id == owner.id,
                Notification.type == NotificationType.PLAN_LIMIT_REACHED,
                Notification.created_at >= recent_cutoff,
            )
        )

        if result.scalar_one_or_none() is not None:
            return

        plan_name = plan.name if plan is not None else "your plan"

        if plan is not None:
            body = (
                f"{plan_name} allows "
                f"{plan.max_messages_per_month} messages/month, "
                "and you've reached the limit. New messages are receiving "
                "a fallback reply until you upgrade or the month resets."
            )
        else:
            body = "You've reached your plan's monthly message limit."

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

    async def _send_stored_reply(
        self,
        conversation: Conversation,
        external_conversation_id: str,
        adapter,
        content: str,
        role: MessageRole,
    ) -> None:
        """Persist a reply before delivering it through the platform."""

        await self.conversation_service.add_message(
            conversation,
            role=role,
            content=content,
        )

        await self.db.commit()

        try:
            await adapter.send_text(
                external_conversation_id,
                content,
            )
        except Exception:
            logger.error(
                (
                    "Failed to deliver stored reply for conversation %s"
                ),
                conversation.id,
                exc_info=True,
            )

    async def _send_media_processing_failure(
        self,
        conversation: Conversation,
        external_conversation_id: str,
        adapter,
        content: str,
    ) -> None:
        """Persist and deliver a media-processing failure response."""

        await self._send_stored_reply(
            conversation=conversation,
            external_conversation_id=external_conversation_id,
            adapter=adapter,
            content=content,
            role=MessageRole.AGENT,
        )

    async def _find_receipt_target_order(
        self,
        owner_id: uuid.UUID,
        customer_id: uuid.UUID,
    ) -> Order | None:
        """Find the newest order still awaiting customer payment.

        Never attaches a receipt to an order that is already paid, cancelled,
        refunded, or delivered.
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
        """Analyze an incoming image and optionally attach a payment receipt.

        Returns:
            (True, None)
                A response has already been sent and normal generation should
                stop.

            (False, enriched_text)
                Image analysis succeeded and the enriched text should continue
                through normal routing, RAG, product search, and generation.

        Payment handling is deliberately conservative:

            image
              -> vision description
              -> receipt classification
              -> attach receipt
              -> owner reviews
              -> owner manually confirms payment

        The pipeline never marks an order as PAID based solely on AI vision.
        """

        if not incoming.media_file_id:
            return False, incoming.text

        try:
            image_bytes, mime_type = await adapter.download_media(
                incoming.media_file_id
            )

            if not image_bytes:
                raise ValueError("Platform returned an empty image payload.")

            description = (
                await self.router_service.ai_provider.describe_image(
                    image_bytes,
                    mime_type,
                )
            )

            description = (description or "").strip()

            if not description:
                raise ValueError(
                    "Gemini returned an empty image description."
                )

        except Exception:
            logger.warning(
                (
                    "Image analysis failed for message %s in "
                    "conversation %s"
                ),
                incoming.external_message_id,
                conversation.id,
                exc_info=True,
            )

            await self._send_media_processing_failure(
                conversation=conversation,
                external_conversation_id=(
                    incoming.external_conversation_id
                ),
                adapter=adapter,
                content=IMAGE_ANALYSIS_FAILURE_REPLY,
            )

            return True, None

        caption_note = ""

        if incoming.text and incoming.text.strip():
            caption_note = (
                f' Customer caption: "{incoming.text.strip()}"'
            )

        enriched_text = (
            "[Customer sent a photo."
            f"{caption_note} "
            f"What the photo shows: {description}]"
        )

        try:
            await self.conversation_service.update_message_content(
                inbound_message,
                enriched_text,
            )
            await self.db.commit()
        except Exception:
            await self.db.rollback()

            logger.error(
                (
                    "Failed to persist analyzed image content for "
                    "message %s"
                ),
                incoming.external_message_id,
                exc_info=True,
            )

        if customer is None:
            return False, enriched_text

        target_order = await self._find_receipt_target_order(
            owner.id,
            customer.id,
        )

        if target_order is None:
            return False, enriched_text

        classification = await self._classify_payment_receipt(
            description
        )

        if classification != PAYMENT_RECEIPT_LABEL:
            return False, enriched_text

        try:
            await self.order_service.attach_receipt(
                owner.id,
                target_order.id,
                incoming.media_file_id,
            )

            reply_text = _PAYMENT_RECEIPT_REPLY_TEMPLATE.format(
                order_id=str(target_order.id)[:8].upper(),
            )

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=reply_text,
            )

            await self.db.commit()

            try:
                await adapter.send_text(
                    incoming.external_conversation_id,
                    reply_text,
                )
            except Exception:
                logger.error(
                    (
                        "Payment receipt was attached to order %s but "
                        "customer notification failed."
                    ),
                    target_order.id,
                    exc_info=True,
                )

            return True, None

        except Exception:
            await self.db.rollback()

            logger.error(
                (
                    "Failed to attach payment receipt for order %s "
                    "from message %s"
                ),
                target_order.id,
                incoming.external_message_id,
                exc_info=True,
            )

            fallback = (
                "I received your image, but I couldn't attach it to the "
                "pending order automatically. Please send the receipt "
                "again or contact the team so we can review it."
            )

            await self._send_media_processing_failure(
                conversation=conversation,
                external_conversation_id=(
                    incoming.external_conversation_id
                ),
                adapter=adapter,
                content=fallback,
            )

            return True, None

    async def _classify_payment_receipt(
        self,
        image_description: str,
    ) -> str | None:
        """Classify an analyzed image as a payment receipt or not.

        Failure is intentionally treated as non-receipt. This prevents a
        provider outage or malformed response from causing an image to be
        attached as a financial document by accident.
        """

        try:
            classification = (
                await self.router_service.ai_provider.classify(
                    image_description,
                    labels=[
                        PAYMENT_RECEIPT_LABEL,
                        NON_PAYMENT_IMAGE_LABEL,
                    ],
                )
            )

            classification = (classification or "").strip().lower()

            if classification == PAYMENT_RECEIPT_LABEL:
                return PAYMENT_RECEIPT_LABEL

            return NON_PAYMENT_IMAGE_LABEL

        except Exception:
            logger.warning(
                "Payment receipt classification failed.",
                exc_info=True,
            )

            return NON_PAYMENT_IMAGE_LABEL

    async def _transcribe_voice(
        self,
        incoming: IncomingMessage,
        adapter,
        inbound_message: Message,
    ) -> str | None:
        """Download and transcribe a voice message.

        Returns the transcript when successful. A provider or download
        failure returns None and is handled by handle_incoming().
        """

        if not incoming.media_file_id:
            return None

        try:
            audio_bytes, mime_type = await adapter.download_media(
                incoming.media_file_id
            )

            if not audio_bytes:
                raise ValueError(
                    "Platform returned an empty audio payload."
                )

            transcript = (
                await self.router_service.ai_provider.transcribe_audio(
                    audio_bytes,
                    mime_type,
                )
            )

            transcript = (transcript or "").strip()

            if not transcript:
                raise ValueError(
                    "AI provider returned an empty voice transcript."
                )

        except Exception:
            logger.warning(
                "Voice transcription failed for message %s",
                incoming.external_message_id,
                exc_info=True,
            )
            return None

        try:
            await self.conversation_service.update_message_content(
                inbound_message,
                f"[Voice message transcript] {transcript}",
            )

            await self.db.commit()

        except Exception:
            await self.db.rollback()

            logger.error(
                (
                    "Failed to persist voice transcript for message %s"
                ),
                incoming.external_message_id,
                exc_info=True,
            )

        return transcript

    async def _resolve_agent(
        self,
        owner: User,
        conversation: Conversation,
        integration: PlatformIntegration,
        effective_text: str | None,
    ) -> Agent:
        """Resolve the agent responsible for the current message."""

        if effective_text:
            return await self.router_service.route(
                owner.id,
                effective_text,
            )

        return await self._pick_agent_without_ai(
            owner.id,
            conversation,
            integration,
        )

    async def _pick_agent_without_ai(
        self,
        owner_id: uuid.UUID,
        conversation: Conversation,
        integration: PlatformIntegration,
    ) -> Agent:
        """Select an agent without invoking the AI router."""

        if conversation.agent_id is not None:
            try:
                return await self.router_service.agent_service.get_agent(
                    owner_id,
                    conversation.agent_id,
                )
            except HTTPException:
                pass

        default_agent_id = integration.settings.get(
            "default_agent_id"
        )

        if default_agent_id:
            try:
                return await self.router_service.agent_service.get_agent(
                    owner_id,
                    uuid.UUID(str(default_agent_id)),
                )
            except (HTTPException, ValueError):
                pass

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

    async def _build_reply(
        self,
        owner: User,
        conversation: Conversation,
        incoming: IncomingMessage,
        agent: Agent,
        customer,
        effective_text: str | None,
    ) -> tuple[str, Product | None]:
        """Build the AI response using RAG, memory, products, and tools."""

        if not effective_text:
            return (
                _NON_TEXT_ACKNOWLEDGEMENTS.get(
                    incoming.message_type,
                    "Got it, thanks!",
                ),
                None,
            )

        knowledge_results = await self.knowledge_service.search(
            owner.id,
            effective_text,
            agent_id=agent.id,
            top_k=3,
        )

        memory_results = await self.memory_service.search(
            owner.id,
            effective_text,
            agent_id=agent.id,
            top_k=3,
        )

        product_results = await self.product_service.search(
            owner.id,
            effective_text,
            top_k=3,
        )

        history = await self.conversation_service.get_recent_messages(
            conversation.id,
            limit=10,
        )

        system_instruction = self._build_system_instruction(
            agent=agent,
            knowledge_results=knowledge_results,
            memory_results=memory_results,
            product_results=product_results,
        )

        prompt = self._build_prompt(
            history=history,
            latest_text=effective_text,
        )

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

        reply_text = (reply_text or "").strip()

        if not reply_text:
            raise RuntimeError(
                "AI provider returned an empty reply."
            )

        top_product = None

        if product_results:
            best_product, best_score = product_results[0]

            if best_score >= PRODUCT_PHOTO_MIN_SCORE:
                top_product = best_product

        return reply_text, top_product

    async def _send_product_photo(
        self,
        adapter,
        incoming: IncomingMessage,
        product: Product | None,
    ) -> None:
        """Send a relevant product image without blocking the text reply."""

        if product is None:
            return

        images = product.images or []

        if not images:
            return

        try:
            caption = _build_product_photo_caption(product)

            await adapter.send_photo(
                incoming.external_conversation_id,
                images[0],
                caption,
            )

        except Exception:
            logger.warning(
                "Failed to send product photo for product %s.",
                product.id,
                exc_info=True,
            )

    @staticmethod
    def _build_system_instruction(
        agent: Agent,
        knowledge_results,
        memory_results,
        product_results,
    ) -> str:
        """Build the provider-independent system instruction."""

        parts = [agent.instructions]

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
            if part and part.strip()
        )

    @staticmethod
    def _build_prompt(
        history: list[Message],
        latest_text: str,
    ) -> str:
        """Build the conversational prompt from recent history."""

        lines: list[str] = []

        for message in history:
            if message.role == MessageRole.USER:
                lines.append(
                    f"Customer: {message.content}"
                )

            elif message.role == MessageRole.AGENT:
                lines.append(
                    f"You: {message.content}"
                )

        lines.append(f"Customer: {latest_text}")
        lines.append("You:")

        return "\n".join(lines)

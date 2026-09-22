"""MessagingPipeline — the piece that actually strings together every
previous milestone: an incoming platform message becomes a routed,
context-aware, generated reply, sent back through the same platform.

Flow for handle_incoming():
  1. adapter.parse_incoming(payload)              -> normalized IncomingMessage
  2. ConversationService.get_or_create_conversation -> thread identity
  3. store the incoming message
  4. IMAGE/VOICE only: download the media and actually look at/listen
     to it (_handle_image_message / _transcribe_voice) -> real content
     instead of a canned "thanks, I got that" acknowledgement. A photo
     that reads as a payment screenshot and matches a customer's order
     still awaiting payment gets auto-attached via OrderService — see
     _handle_image_message's docstring for why that stops short of
     auto-confirming payment.
  5. RouterService.route()                         -> which agent answers (Milestone 3)
  6. KnowledgeService.search() + MemoryService.search() -> RAG context (Milestone 4)
  7. build a prompt from agent instructions + context + recent history
  8. AIProvider.generate()                         -> the reply text (Milestone 2)
  9. store the outgoing message
  10. adapter.send_text()                          -> actually deliver it

Every step reuses a service built in an earlier milestone rather than
reimplementing anything - this file is orchestration, not new logic.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from fastapi import HTTPException, status

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

# Order statuses/payment states we still consider "waiting on this
# customer to pay" — a payment screenshot only auto-attaches to an
# order in one of these states. An order already PAID, CANCELLED, or
# REFUNDED is not a valid receipt target even if it's the customer's
# most recent order.
_AWAITING_PAYMENT_STATUSES = {PaymentStatus.UNPAID, PaymentStatus.AWAITING_CONFIRMATION}
_CLOSED_ORDER_STATUSES = {OrderStatus.CANCELLED, OrderStatus.REFUNDED, OrderStatus.DELIVERED}

# Cosine similarity floor before we consider a product match "on topic"
# enough to send its photo unprompted. product_service.search() always
# returns its top_k best-effort matches even for queries with no real
# product relevance (e.g. "what are your hours") — this threshold is what
# stops PersonaAI from sending a random product photo on every message.
PRODUCT_PHOTO_MIN_SCORE = 0.5


def _build_product_photo_caption(product: Product) -> str:
    """Name + price was the whole caption before — a customer asking
    "do you have crocs?" got a photo with no idea what sizes/colors
    (the product's `variants`, e.g. {"name": "Size 42, Red", ...}) are
    actually available, or whether it's in stock at all. This is what
    the fix for that actually sends."""
    lines = [f"{product.name} — {product.price} {product.currency}"]

    variant_names = [v.get("name") for v in product.variants if v.get("name")]
    if variant_names:
        lines.append(f"Available: {', '.join(variant_names)}")

    if product.inventory is not None:
        lines.append("In stock" if product.inventory > 0 else "Currently out of stock")

    if product.description:
        lines.append(product.description[:200])

    caption = "\n".join(lines)
    return caption[:1024]  # Telegram/WhatsApp caption length caps; adapters also enforce this, belt-and-suspenders


_NON_TEXT_ACKNOWLEDGEMENTS = {
    # IMAGE and VOICE are handled separately now — see
    # _handle_image_message / _transcribe_voice — and only fall back to
    # a canned acknowledgement here if analysis itself fails (download
    # error, AI provider error, etc.), not as the normal path.
    MessageType.IMAGE: "Thanks for the image - I've received it and will follow up shortly.",
    MessageType.DOCUMENT: "Thanks for the document - I've received it and will follow up shortly.",
    MessageType.VOICE: "Thanks for the voice message - I've received it and will follow up shortly.",
    MessageType.LOCATION: "Thanks for sharing your location - noted.",
    MessageType.VIDEO: "Thanks for the video - I've received it and will follow up shortly.",
    MessageType.CONTACT: "Thanks for sharing that contact - noted.",
    MessageType.OTHER: "Got it, thanks!",
}

_WEEKDAY_KEYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]


def _after_hours_reply(settings: dict) -> str | None:
    """Returns a canned after-hours reply if `settings["business_hours"]` is
    configured, enabled, and the current time (in the configured timezone)
    falls outside every window for today — otherwise None, meaning "proceed
    with a normal AI-generated reply".

    Deliberately simple: one open/close window per day, no holiday
    calendar, no per-agent overrides. Format:
        {"enabled": true, "timezone": "Africa/Lagos",
         "hours": {"mon": ["09:00", "17:00"], ...}, "message": "..."}
    A day omitted from `hours` (or an empty list) means closed all day.
    Malformed configuration fails open (treated as "no restriction") rather
    than silently blocking every message.
    """
    business_hours = settings.get("business_hours")
    if not business_hours or not business_hours.get("enabled"):
        return None

    try:
        import zoneinfo
        from datetime import datetime as _dt

        tz = zoneinfo.ZoneInfo(business_hours.get("timezone", "UTC"))
        now = _dt.now(tz)
        today_key = _WEEKDAY_KEYS[now.weekday()]
        window = business_hours.get("hours", {}).get(today_key)
        if not window:
            is_open = False
        else:
            open_str, close_str = window[0], window[1]
            open_time = _dt.strptime(open_str, "%H:%M").time()
            close_time = _dt.strptime(close_str, "%H:%M").time()
            is_open = open_time <= now.time() <= close_time
    except Exception:
        logger.warning("Malformed business_hours settings; ignoring", exc_info=True)
        return None

    if is_open:
        return None
    return business_hours.get(
        "message", "Thanks for reaching out! We're currently outside business hours and will reply as soon as we're back."
    )


class MessagingPipeline:
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
        self, owner: User, integration: PlatformIntegration, raw_payload: dict
    ) -> None:
        adapter = build_adapter(integration)
        try:
            incoming = adapter.parse_incoming(raw_payload)
            if incoming is None:
                return

            conversation = await self.conversation_service.get_or_create_conversation(
                owner_id=owner.id,
                platform=integration.platform,
                external_conversation_id=incoming.external_conversation_id,
                external_user_id=incoming.external_user_id,
                external_user_name=incoming.external_user_name,
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

            if incoming.external_message_id and integration.settings.get("read_receipts", True):
                try:
                    await adapter.mark_read(
                        incoming.external_message_id, show_typing=integration.settings.get("typing_indicator", True)
                    )
                except Exception:
                    # Read receipts/typing indicators are a nicety, never worth failing the reply over.
                    logger.debug("mark_read failed for message %s", incoming.external_message_id, exc_info=True)

            customer = None
            if incoming.external_user_id:
                customer = await self.customer_service.get_or_create_customer(
                    owner_id=owner.id,
                    platform=integration.platform,
                    external_user_id=incoming.external_user_id,
                    display_name=incoming.external_user_name,
                )
                await self.db.commit()

            if conversation.assigned_to_human or not integration.settings.get("auto_reply", True):
                # A human is handling this thread, or the owner has switched
                # auto-reply off for this integration — store the message and
                # stop. No agent routing, no AI call, no auto-reply.
                return

            after_hours_reply = _after_hours_reply(integration.settings)
            if after_hours_reply is not None:
                await self.conversation_service.add_message(
                    conversation, role=MessageRole.SYSTEM, content=after_hours_reply
                )
                await self.db.commit()
                await adapter.send_text(incoming.external_conversation_id, after_hours_reply)
                return

            # Plan enforcement's one non-HTTP checkpoint: everything past this
            # point costs a Gemini call (routing when there's more than one
            # active agent, then the reply generation itself). A message that
            # arrives over quota still gets stored above (that's just a DB
            # write), but never reaches the AI — this is the fix for the
            # "unlimited messages on a $0 plan" gap flagged in
            # app/core/plan_limits.py's docstring.
            limit_reached, plan = await check_message_limit(self.db, owner.id)
            if limit_reached:
                await self._handle_message_limit_reached(owner, integration, conversation, adapter, plan)
                return

            # effective_text is what actually drives routing + reply
            # generation below. For a TEXT message it's just the text.
            # For IMAGE/VOICE it starts as None and gets filled in by
            # actually looking at/listening to the media — this is the
            # fix for photos and voice notes being stored but never
            # analyzed (previously every non-text message got a canned
            # "thanks, I got that" no matter what it contained).
            effective_text = incoming.text

            if incoming.message_type == MessageType.IMAGE and incoming.media_file_id:
                handled, effective_text = await self._handle_image_message(
                    owner, conversation, customer, incoming, adapter, inbound_message
                )
                if handled:
                    return
            elif incoming.message_type == MessageType.VOICE and incoming.media_file_id:
                effective_text = await self._transcribe_voice(incoming, adapter, inbound_message)

            try:
                if effective_text:
                    agent = await self.router_service.route(owner.id, effective_text)
                else:
                    agent = await self._pick_agent_without_ai(owner.id, conversation, integration)
                reply_text, top_product = await self._build_reply(
                    owner, conversation, incoming, agent, customer, effective_text
                )
            except Exception:
                # Previously uncaught — an AI failure anywhere in routing
                # (Router.route() calls Gemini to classify which agent,
                # when there's more than one active) or reply generation
                # (missing/invalid GEMINI_API_KEY, quota exhausted, Gemini
                # having an outage) propagated all the way out of
                # handle_incoming with no fallback, so the customer got no
                # reply at all and nothing indicated why. Every other
                # failure point in this file (image analysis, message
                # limits) already degrades to a sent reply instead of
                # silence; this is that same treatment for the actual
                # routing + reply-generation steps.
                logger.error(
                    "Routing or reply generation failed for conversation %s", conversation.id, exc_info=True
                )
                agent = None
                reply_text, top_product = (
                    "Sorry, something went wrong on our end. We'll follow up shortly.",
                    None,
                )

            await self.conversation_service.add_message(
                conversation,
                role=MessageRole.AGENT,
                content=reply_text,
                agent_id=agent.id if agent is not None else None,
            )
            await self.db.commit()

            if top_product is not None and top_product.images:
                try:
                    caption = _build_product_photo_caption(top_product)
                    await adapter.send_photo(incoming.external_conversation_id, top_product.images[0], caption)
                except Exception:
                    # A broken image URL shouldn't block the actual text reply.
                    logger.warning(
                        "Failed to send product photo for product %s", top_product.id, exc_info=True
                    )

            await adapter.send_text(incoming.external_conversation_id, reply_text)

        finally:
            aclose = getattr(adapter, "aclose", None)
            if aclose is not None:
                await aclose()

    async def _handle_message_limit_reached(
        self,
        owner: User,
        integration: PlatformIntegration,
        conversation: Conversation,
        adapter,
        plan,
    ) -> None:
        """The contact still gets a reply — just not an AI-generated one —
        and the owner gets told once per day, not on every message while
        they're over quota (that would just be a second way for a $0
        account to spam their own notification feed)."""
        reply_text = (
            "Thanks for your message! We've reached our messaging limit for this month — "
            "a team member will get back to you as soon as possible."
        )
        await self.conversation_service.add_message(conversation, role=MessageRole.SYSTEM, content=reply_text)
        await self.db.commit()
        await adapter.send_text(conversation.external_conversation_id, reply_text)

        recent_cutoff = datetime.now(timezone.utc) - timedelta(hours=24)
        already_notified = await self.db.execute(
            select(Notification.id).where(
                Notification.owner_id == owner.id,
                Notification.type == NotificationType.PLAN_LIMIT_REACHED,
                Notification.created_at >= recent_cutoff,
            )
        )
        if already_notified.scalar_one_or_none() is not None:
            return

        plan_name = plan.name if plan is not None else "your plan"
        await NotificationService(self.db).create(
            owner_id=owner.id,
            type_=NotificationType.PLAN_LIMIT_REACHED,
            title="Monthly message limit reached",
            body=(
                f"{plan_name} allows {plan.max_messages_per_month} messages/month, and you've hit it. "
                f"New messages are getting a hold-tight reply instead of an AI response until you "
                f"upgrade or the month resets."
                if plan is not None
                else "You've reached your plan's monthly message limit."
            ),
            context={"integration_id": str(integration.id)},
        )
        await self.db.commit()

    async def _find_receipt_target_order(self, owner_id: uuid.UUID, customer_id: uuid.UUID) -> Order | None:
        """The most recent order for this customer that's genuinely
        still waiting on payment. A payment screenshot only auto-attaches
        if one exists — if the customer's most recent order is already
        PAID (or there's no order at all), we don't guess."""
        orders = await self.order_service.list_orders(owner_id, customer_id=customer_id)
        for order in orders:  # already sorted newest-first
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
        """Actually looks at an incoming photo instead of just
        acknowledging it. Returns (handled, effective_text):

          - handled=True: a reply was already sent from inside this
            method (the payment-receipt path, or a failure fallback) —
            handle_incoming should return immediately.
          - handled=False: the image wasn't a receipt (or there's no
            order to attach it to). effective_text describes what the
            photo actually shows, which the caller feeds into the
            normal routing + RAG + reply-generation flow, same as if
            the customer had typed it — this is what makes "does this
            look like the one in the picture?" answerable at all.

        A download or AI-provider failure degrades to the canned IMAGE
        acknowledgement (handled=True) rather than leaving the customer
        without any reply — vision analysis is an enhancement, not a
        new single point of failure for the whole pipeline.
        """
        try:
            image_bytes, mime_type = await adapter.download_media(incoming.media_file_id)
            description = await self.router_service.ai_provider.describe_image(image_bytes, mime_type)
        except Exception:
            logger.warning(
                "Image analysis failed for message %s in conversation %s",
                incoming.external_message_id,
                conversation.id,
                exc_info=True,
            )
            fallback = _NON_TEXT_ACKNOWLEDGEMENTS[MessageType.IMAGE]
            await self.conversation_service.add_message(conversation, role=MessageRole.AGENT, content=fallback)
            await self.db.commit()
            await adapter.send_text(incoming.external_conversation_id, fallback)
            return True, None

        caption_note = f' Caption: "{incoming.text.strip()}"' if incoming.text and incoming.text.strip() else ""
        enriched_text = f"[Customer sent a photo.{caption_note} What the photo shows: {description}]"
        await self.conversation_service.update_message_content(inbound_message, enriched_text)
        await self.db.commit()

        if customer is not None:
            target_order = await self._find_receipt_target_order(owner.id, customer.id)
            if target_order is not None:
                try:
                    classification = await self.router_service.ai_provider.classify(
                        description, labels=["payment_receipt_or_bank_transfer_confirmation", "something_else"]
                    )
                except Exception:
                    # Ambiguous vision result — treat conservatively as
                    # "not a receipt" rather than risking a wrong auto-attach.
                    classification = "something_else"

                if classification == "payment_receipt_or_bank_transfer_confirmation":
                    # attach_receipt only sets payment_status to
                    # AWAITING_CONFIRMATION and notifies the owner — it does
                    # NOT mark the order paid. The owner still reviews and
                    # confirms manually (OrderService.confirm_payment),
                    # exactly as if the receipt had been forwarded to them
                    # directly. Auto-confirming payment from a vision guess
                    # would be a real money mistake waiting to happen; this
                    # automation only removes the "customer's photo silently
                    # goes nowhere" failure mode, not the human review step.
                    await self.order_service.attach_receipt(owner.id, target_order.id, incoming.media_file_id)
                    reply_text = (
                        f"Thanks — we've received your payment screenshot for order "
                        f"#{str(target_order.id)[:8].upper()}. We'll review and confirm it shortly."
                    )
                    await self.conversation_service.add_message(
                        conversation, role=MessageRole.AGENT, content=reply_text
                    )
                    await self.db.commit()
                    await adapter.send_text(incoming.external_conversation_id, reply_text)
                    return True, None

        return False, enriched_text

    async def _transcribe_voice(
        self, incoming: IncomingMessage, adapter, inbound_message: Message
    ) -> str | None:
        """Downloads and transcribes a voice note. Returns the
        transcript (feeding it into the normal reply flow, same as
        _handle_image_message's effective_text), or None if download/
        transcription failed or came back empty — the caller falls
        back to the canned VOICE acknowledgement in that case."""
        try:
            audio_bytes, mime_type = await adapter.download_media(incoming.media_file_id)
            transcript = await self.router_service.ai_provider.transcribe_audio(audio_bytes, mime_type)
        except Exception:
            logger.warning(
                "Voice transcription failed for message %s", incoming.external_message_id, exc_info=True
            )
            return None

        transcript = (transcript or "").strip()
        if not transcript:
            return None

        await self.conversation_service.update_message_content(
            inbound_message, f"[Voice message transcript] {transcript}"
        )
        await self.db.commit()
        return transcript

    async def _pick_agent_without_ai(self, owner_id: uuid.UUID, conversation: Conversation, integration: PlatformIntegration) -> Agent:
        """For non-text messages we skip Router's classify() call entirely —
        there's no message text to classify, and the acknowledgement reply
        doesn't need agent-specific instructions anyway. Prefers whichever
        agent is already handling this conversation, then an integration's
        configured default agent, then falls back to the first active agent."""
        if conversation.agent_id is not None:
            try:
                return await self.router_service.agent_service.get_agent(owner_id, conversation.agent_id)
            except HTTPException:
                pass  # agent was deleted since — fall through to picking a fresh one

        default_agent_id = integration.settings.get("default_agent_id")
        if default_agent_id:
            try:
                return await self.router_service.agent_service.get_agent(owner_id, uuid.UUID(default_agent_id))
            except (HTTPException, ValueError):
                pass  # configured default agent is gone/invalid — fall through

        active_agents = [
            agent
            for agent in await self.router_service.agent_service.list_agents(owner_id)
            if agent.status == AgentStatus.ACTIVE
        ]
        if not active_agents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account has no active agents to handle messages.",
            )
        return active_agents[0]

    async def _build_reply(
        self,
        owner: User,
        conversation: Conversation,
        incoming: IncomingMessage,
        agent,
        customer,
        effective_text: str | None,
    ) -> tuple[str, Product | None]:
        if not effective_text:
            return _NON_TEXT_ACKNOWLEDGEMENTS.get(incoming.message_type, "Got it, thanks!"), None

        knowledge_results = await self.knowledge_service.search(
            owner.id, effective_text, agent_id=agent.id, top_k=3
        )
        memory_results = await self.memory_service.search(
            owner.id, effective_text, agent_id=agent.id, top_k=3
        )
        product_results = await self.product_service.search(owner.id, effective_text, top_k=3)
        history = await self.conversation_service.get_recent_messages(conversation.id, limit=10)

        system_instruction = self._build_system_instruction(
            agent, knowledge_results, memory_results, product_results
        )
        prompt = self._build_prompt(history, effective_text)

        if customer is not None:
            # Real tool-calling: the AI itself decides whether this message
            # needs search_product/create_order, or just a plain reply — see
            # AIProvider.generate_with_tools's docstring for why this is a
            # concrete (not abstract) method and what falls back to plain
            # generate() when a provider doesn't implement real tool-calling.
            context = ToolContext(
                db=self.db, owner_id=owner.id, customer=customer, conversation_id=conversation.id
            )

            async def tool_executor(tool_name: str, arguments: dict) -> dict:
                return await execute_tool(tool_name, arguments, context)

            reply_text = await self.router_service.ai_provider.generate_with_tools(
                prompt,
                tools=default_tool_definitions(),
                tool_executor=tool_executor,
                system_instruction=system_instruction,
                temperature=agent.temperature,
            )
        else:
            # No resolvable customer identity (e.g. adapter didn't supply a
            # sender id) — tools that create orders need a Customer to
            # attach the order to, so we skip tool-calling and just reply.
            reply_text = await self.router_service.ai_provider.generate(
                prompt, system_instruction=system_instruction, temperature=agent.temperature
            )

        top_product = None
        if product_results:
            best_product, best_score = product_results[0]
            if best_score >= PRODUCT_PHOTO_MIN_SCORE:
                top_product = best_product

        return reply_text, top_product

    @staticmethod
    def _build_system_instruction(agent, knowledge_results, memory_results, product_results) -> str:
        parts = [agent.instructions]

        if knowledge_results:
            knowledge_lines = "\n".join(f"- {chunk.content}" for chunk, _score in knowledge_results)
            parts.append(f"Relevant knowledge base entries:\n{knowledge_lines}")

        if memory_results:
            memory_lines = "\n".join(f"- {entry.content}" for entry, _score in memory_results)
            parts.append(f"Relevant things you know/remember:\n{memory_lines}")

        if product_results:
            product_lines = "\n".join(
                f"- {p.name}: {p.price} {p.currency}"
                + (f" ({p.discount_percent:g}% off)" if p.discount_percent else "")
                + (f" - {p.description}" if p.description else "")
                for p, _score in product_results
            )
            parts.append(f"Relevant products/services you can sell:\n{product_lines}")

        return "\n\n".join(parts)

    @staticmethod
    def _build_prompt(history: list[Message], latest_text: str) -> str:
        lines = []
        for message in history:
            if message.role == MessageRole.USER:
                lines.append(f"Customer: {message.content}")
            elif message.role == MessageRole.AGENT:
                lines.append(f"You: {message.content}")
        lines.append(f"Customer: {latest_text}")
        lines.append("You:")
        return "\n".join(lines)

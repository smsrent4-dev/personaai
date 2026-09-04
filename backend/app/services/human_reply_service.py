"""HumanReplyService - lets a person send a message through the
Conversation Viewer (after taking over a conversation) using the exact
same adapter the automated pipeline would have used.

A human-authored message is stored with role=AGENT and agent_id=None
(automated replies always have agent_id set - see
MessagingPipeline.handle_incoming) rather than adding a new MessageRole
value. Documented here since it's a convention, not something visible
in the enum itself.
"""
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.integration import PlatformIntegration
from app.models.message import Message, MessageRole
from app.services.conversation_service import ConversationService
from app.services.platforms.registry import build_adapter


class HumanReplyService:
    def __init__(self, db: AsyncSession):
        self.db = db
        self.conversation_service = ConversationService(db)

    async def send(self, owner_id, conversation: Conversation, text: str) -> Message:
        result = await self.db.execute(
            select(PlatformIntegration).where(
                PlatformIntegration.owner_id == owner_id, PlatformIntegration.platform == conversation.platform
            )
        )
        integration = result.scalar_one_or_none()
        if integration is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No active {conversation.platform.value} integration to send through.",
            )

        adapter = build_adapter(integration)
        try:
            await adapter.send_text(conversation.external_conversation_id, text)
        finally:
            aclose = getattr(adapter, "aclose", None)
            if aclose is not None:
                await aclose()

        message = await self.conversation_service.add_message(
            conversation, role=MessageRole.AGENT, content=text, agent_id=None
        )
        await self.db.commit()
        return message

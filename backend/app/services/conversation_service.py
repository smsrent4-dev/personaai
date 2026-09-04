"""ConversationService — conversation threads and their message history.

get_or_create_conversation is the identity mapping that makes
multi-turn conversations work: the same (owner, platform,
external_conversation_id) triple always resolves to the same
Conversation row, so message history accumulates correctly across
separate webhook calls.
"""
import uuid
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation, ConversationStatus
from app.models.message import Message, MessageRole, MessageType
from app.models.platform_enums import Platform
from app.models.notification import NotificationType
from app.services.notification_service import NotificationService


class ConversationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_or_create_conversation(
        self,
        owner_id: uuid.UUID,
        platform: Platform,
        external_conversation_id: str,
        external_user_id: str | None = None,
        external_user_name: str | None = None,
    ) -> Conversation:
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.owner_id == owner_id,
                Conversation.platform == platform,
                Conversation.external_conversation_id == external_conversation_id,
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is not None:
            # Keep the display name fresh (Telegram usernames can change).
            if external_user_name and conversation.external_user_name != external_user_name:
                conversation.external_user_name = external_user_name
                await self.db.flush()
            return conversation

        conversation = Conversation(
            owner_id=owner_id,
            platform=platform,
            external_conversation_id=external_conversation_id,
            external_user_id=external_user_id,
            external_user_name=external_user_name,
        )
        self.db.add(conversation)
        await self.db.flush()

        await NotificationService(self.db).create(
            owner_id=owner_id,
            type_=NotificationType.NEW_LEAD,
            title="New conversation",
            body=f"{external_user_name or external_conversation_id} started a conversation on {platform.value}.",
            context={"conversation_id": str(conversation.id)},
        )

        return conversation

    async def add_message(
        self,
        conversation: Conversation,
        role: MessageRole,
        content: str | None,
        message_type: MessageType = MessageType.TEXT,
        agent_id: uuid.UUID | None = None,
        external_message_id: str | None = None,
        media_file_id: str | None = None,
        latitude: float | None = None,
        longitude: float | None = None,
        platform_metadata: dict | None = None,
    ) -> Message:
        message = Message(
            conversation_id=conversation.id,
            owner_id=conversation.owner_id,
            agent_id=agent_id,
            role=role,
            message_type=message_type,
            content=content,
            external_message_id=external_message_id,
            media_file_id=media_file_id,
            latitude=latitude,
            longitude=longitude,
            platform_metadata=platform_metadata,
        )
        self.db.add(message)
        conversation.last_message_at = datetime.now(timezone.utc)
        if agent_id is not None:
            conversation.agent_id = agent_id
        await self.db.flush()
        return message

    async def update_message_content(self, message: Message, content: str) -> Message:
        """Replaces a stored message's content after the fact — used
        when an inbound IMAGE/VOICE message's real "content" (a vision
        description, a transcript) is only known after analysis runs,
        which happens after the message row is already stored. Without
        this, conversation history (get_recent_messages, used to build
        the prompt for later replies) would show a blank/None line for
        that turn forever, and the AI would effectively forget the
        photo or voice note ever happened."""
        message.content = content
        await self.db.flush()
        return message

    async def list_conversations(
        self,
        owner_id: uuid.UUID,
        platform: Platform | None = None,
        conversation_status: ConversationStatus | None = None,
        agent_id: uuid.UUID | None = None,
        search: str | None = None,
    ) -> list[Conversation]:
        stmt = select(Conversation).where(Conversation.owner_id == owner_id)
        if platform is not None:
            stmt = stmt.where(Conversation.platform == platform)
        if conversation_status is not None:
            stmt = stmt.where(Conversation.status == conversation_status)
        if agent_id is not None:
            stmt = stmt.where(Conversation.agent_id == agent_id)
        if search:
            like = f"%{search}%"
            stmt = stmt.where(
                (Conversation.external_user_name.ilike(like))
                | (Conversation.external_conversation_id.ilike(like))
            )
        stmt = stmt.order_by(Conversation.last_message_at.desc().nulls_last())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def set_tags(self, owner_id: uuid.UUID, conversation_id: uuid.UUID, tags: list[str]) -> Conversation:
        conversation = await self.get_conversation(owner_id, conversation_id)
        conversation.tags = tags
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def set_human_takeover(
        self, owner_id: uuid.UUID, conversation_id: uuid.UUID, assigned: bool
    ) -> Conversation:
        conversation = await self.get_conversation(owner_id, conversation_id)
        conversation.assigned_to_human = assigned
        await self.db.commit()
        await self.db.refresh(conversation)
        return conversation

    async def get_conversation(self, owner_id: uuid.UUID, conversation_id: uuid.UUID) -> Conversation:
        result = await self.db.execute(
            select(Conversation).where(
                Conversation.id == conversation_id, Conversation.owner_id == owner_id
            )
        )
        conversation = result.scalar_one_or_none()
        if conversation is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
        return conversation

    async def get_recent_messages(self, conversation_id: uuid.UUID, limit: int = 10) -> list[Message]:
        result = await self.db.execute(
            select(Message)
            .where(Message.conversation_id == conversation_id)
            .order_by(Message.created_at.desc())
            .limit(limit)
        )
        messages = list(result.scalars().all())
        messages.reverse()  # chronological order for prompt-building
        return messages

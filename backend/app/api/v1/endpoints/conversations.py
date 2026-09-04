import csv
import io
import uuid

from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.conversation import ConversationStatus
from app.models.platform_enums import Platform
from app.models.user import User
from app.schemas.conversation import (
    ConversationResponse,
    MessageResponse,
    SendMessageRequest,
    SetTagsRequest,
)
from app.services.conversation_service import ConversationService
from app.services.human_reply_service import HumanReplyService

router = APIRouter(prefix="/conversations", tags=["Conversations"])


@router.get("", response_model=list[ConversationResponse])
async def list_conversations(
    platform: Platform | None = None,
    conversation_status: ConversationStatus | None = None,
    agent_id: uuid.UUID | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ConversationService(db).list_conversations(
        current_user.id, platform=platform, conversation_status=conversation_status, agent_id=agent_id, search=search
    )


@router.get("/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ConversationService(db).get_conversation(current_user.id, conversation_id)


@router.get("/{conversation_id}/messages", response_model=list[MessageResponse])
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    await service.get_conversation(current_user.id, conversation_id)
    return await service.get_recent_messages(conversation_id, limit=limit)


@router.post("/{conversation_id}/tags", response_model=ConversationResponse)
async def set_conversation_tags(
    conversation_id: uuid.UUID,
    data: SetTagsRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await ConversationService(db).set_tags(current_user.id, conversation_id, data.tags)


@router.post("/{conversation_id}/takeover", response_model=ConversationResponse)
async def take_over_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """After this, incoming messages are stored but PersonaAI stops
    auto-replying -- see MessagingPipeline.handle_incoming."""
    return await ConversationService(db).set_human_takeover(current_user.id, conversation_id, True)


@router.post("/{conversation_id}/release", response_model=ConversationResponse)
async def release_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Hands the conversation back to the AI agents."""
    return await ConversationService(db).set_human_takeover(current_user.id, conversation_id, False)


@router.post("/{conversation_id}/messages", response_model=MessageResponse)
async def send_human_message(
    conversation_id: uuid.UUID,
    data: SendMessageRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Sends a message as the human owner, through the same platform
    adapter the AI pipeline uses. Typically used after /takeover."""
    conv_service = ConversationService(db)
    conversation = await conv_service.get_conversation(current_user.id, conversation_id)
    return await HumanReplyService(db).send(current_user.id, conversation, data.content)


@router.get("/{conversation_id}/export")
async def export_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    service = ConversationService(db)
    conversation = await service.get_conversation(current_user.id, conversation_id)
    messages = await service.get_recent_messages(conversation_id, limit=10_000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["timestamp", "role", "message_type", "content"])
    for message in messages:
        writer.writerow(
            [message.created_at.isoformat(), message.role.value, message.message_type.value, message.content or ""]
        )

    filename = f"conversation-{conversation.external_conversation_id}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )

import csv
import io
import uuid
from fastapi import APIRouter, Depends, Response
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.deps import (
    get_current_active_user,
    require_active_subscription,
)
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
router = APIRouter(
    prefix="/conversations",
    tags=["Conversations"],
)
@router.get(
    "",
    response_model=list[ConversationResponse],
)
async def list_conversations(
    platform: Platform | None = None,
    conversation_status: ConversationStatus | None = None,
    agent_id: uuid.UUID | None = None,
    search: str | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """List conversations belonging to the current user.
    Viewing existing conversations does not require an active
    subscription.
    """
    return await ConversationService(db).list_conversations(
        current_user.id,
        platform=platform,
        conversation_status=conversation_status,
        agent_id=agent_id,
        search=search,
    )
@router.get(
    "/{conversation_id}",
    response_model=ConversationResponse,
)
async def get_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """View an existing conversation."""
    return await ConversationService(db).get_conversation(
        current_user.id,
        conversation_id,
    )
@router.get(
    "/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
async def get_conversation_messages(
    conversation_id: uuid.UUID,
    limit: int = 50,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """View messages from an existing conversation."""
    service = ConversationService(db)
    await service.get_conversation(
        current_user.id,
        conversation_id,
    )
    return await service.get_recent_messages(
        conversation_id,
        limit=limit,
    )
@router.post(
    "/{conversation_id}/tags",
    response_model=ConversationResponse,
)
async def set_conversation_tags(
    conversation_id: uuid.UUID,
    data: SetTagsRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Update conversation tags.
    This is account management rather than AI usage, so an owner can
    still organize existing conversations while their subscription is
    inactive.
    """
    return await ConversationService(db).set_tags(
        current_user.id,
        conversation_id,
        data.tags,
    )
@router.post(
    "/{conversation_id}/takeover",
    response_model=ConversationResponse,
)
async def take_over_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Take a conversation over as a human.
    This remains available even if billing is inactive because it is
    important for the business owner to be able to manually handle
    existing customer conversations.
    """
    return await ConversationService(db).set_human_takeover(
        current_user.id,
        conversation_id,
        True,
    )
@router.post(
    "/{conversation_id}/release",
    response_model=ConversationResponse,
)
async def release_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
):
    """Hand a conversation back to PersonaAI.
    An active subscription is required because releasing the
    conversation enables automated AI replies again.
    """
    return await ConversationService(db).set_human_takeover(
        current_user.id,
        conversation_id,
        False,
    )
@router.post(
    "/{conversation_id}/messages",
    response_model=MessageResponse,
)
async def send_human_message(
    conversation_id: uuid.UUID,
    data: SendMessageRequest,
    current_user: User = Depends(require_active_subscription),
    db: AsyncSession = Depends(get_db),
):
    """Send a message as the human owner.
    An active subscription is required because this consumes the
    messaging/integration infrastructure.
    """
    conv_service = ConversationService(db)
    conversation = await conv_service.get_conversation(
        current_user.id,
        conversation_id,
    )
    return await HumanReplyService(db).send(
        current_user.id,
        conversation,
        data.content,
    )
@router.get(
    "/{conversation_id}/export",
)
async def export_conversation(
    conversation_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Export an existing conversation.
    Data export remains available even when the subscription is
    inactive.
    """
    service = ConversationService(db)
    conversation = await service.get_conversation(
        current_user.id,
        conversation_id,
    )
    messages = await service.get_recent_messages(
        conversation_id,
        limit=10_000,
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "timestamp",
            "role",
            "message_type",
            "content",
        ]
    )
    for message in messages:
        writer.writerow(
            [
                message.created_at.isoformat(),
                message.role.value,
                message.message_type.value,
                message.content or "",
            ]
        )
    filename = (
        f"conversation-"
        f"{conversation.external_conversation_id}.csv"
    )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={
            "Content-Disposition": (
                f'attachment; filename="{filename}"'
            )
        },
    )

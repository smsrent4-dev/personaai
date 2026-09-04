import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.conversation import ConversationStatus
from app.models.message import MessageRole, MessageType
from app.models.platform_enums import Platform


class MessageResponse(BaseModel):
    id: uuid.UUID
    role: MessageRole
    message_type: MessageType
    content: str | None
    agent_id: uuid.UUID | None
    media_file_id: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    platform_metadata: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ConversationResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    platform: Platform
    external_conversation_id: str
    external_user_id: str | None
    external_user_name: str | None
    status: ConversationStatus
    tags: list[str]
    assigned_to_human: bool
    last_message_at: datetime | None
    created_at: datetime

    model_config = {"from_attributes": True}


class SetTagsRequest(BaseModel):
    tags: list[str] = Field(default_factory=list, max_length=20)


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4096)

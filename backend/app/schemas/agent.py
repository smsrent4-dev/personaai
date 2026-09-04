import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.agent import AgentStatus, AgentType


class AgentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    description: str | None = None
    avatar_url: str | None = None
    agent_type: AgentType = AgentType.CUSTOM
    instructions: str = ""
    model: str | None = None
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)
    permissions: dict = Field(default_factory=dict)


class AgentUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = None
    avatar_url: str | None = None
    instructions: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    permissions: dict | None = None
    status: AgentStatus | None = None


class AgentResponse(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    avatar_url: str | None
    agent_type: AgentType
    instructions: str
    model: str
    temperature: float
    permissions: dict
    status: AgentStatus
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

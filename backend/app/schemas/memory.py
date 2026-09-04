import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from app.models.memory import MemorySource, MemoryType


class MemoryCreate(BaseModel):
    memory_type: MemoryType
    content: str = Field(min_length=1)
    agent_id: uuid.UUID | None = None


class MemoryResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    memory_type: MemoryType
    source: MemorySource
    content: str
    created_at: datetime

    model_config = {"from_attributes": True}


class MemorySearchRequest(BaseModel):
    query: str = Field(min_length=1)
    agent_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class MemorySearchResult(BaseModel):
    memory: MemoryResponse
    score: float


class MemorySearchResponse(BaseModel):
    results: list[MemorySearchResult]


class TeachRequest(BaseModel):
    statement: str = Field(min_length=1, max_length=2000)
    agent_id: uuid.UUID | None = None

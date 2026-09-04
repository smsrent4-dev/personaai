import uuid
from datetime import datetime

from pydantic import BaseModel, Field, HttpUrl

from app.models.knowledge import KnowledgeSourceType, KnowledgeStatus


class KnowledgeDocumentResponse(BaseModel):
    id: uuid.UUID
    agent_id: uuid.UUID | None
    title: str
    source_type: KnowledgeSourceType
    source_url: str | None
    status: KnowledgeStatus
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeTextCreate(BaseModel):
    title: str = Field(min_length=1, max_length=500)
    content: str = Field(min_length=1)
    source_type: KnowledgeSourceType = KnowledgeSourceType.TEXT
    agent_id: uuid.UUID | None = None


class KnowledgeUrlCreate(BaseModel):
    url: HttpUrl
    title: str | None = Field(default=None, max_length=500)
    agent_id: uuid.UUID | None = None


class KnowledgeSearchRequest(BaseModel):
    query: str = Field(min_length=1)
    agent_id: uuid.UUID | None = None
    top_k: int = Field(default=5, ge=1, le=50)


class KnowledgeSearchResult(BaseModel):
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    document_title: str
    content: str
    score: float


class KnowledgeSearchResponse(BaseModel):
    results: list[KnowledgeSearchResult]

import uuid

from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.memory import (
    MemoryCreate,
    MemoryResponse,
    MemorySearchRequest,
    MemorySearchResponse,
    MemorySearchResult,
)
from app.services.memory_service import MemoryService

router = APIRouter(prefix="/memory", tags=["Memory"])


@router.get("", response_model=list[MemoryResponse])
async def list_memories(
    agent_id: uuid.UUID | None = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await MemoryService(db).list_memories(current_user.id, agent_id=agent_id)


@router.post("", response_model=MemoryResponse, status_code=status.HTTP_201_CREATED)
async def create_memory(
    data: MemoryCreate,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    return await MemoryService(db).create_memory(
        owner_id=current_user.id,
        memory_type=data.memory_type,
        content=data.content,
        agent_id=data.agent_id,
    )


@router.post("/search", response_model=MemorySearchResponse)
async def search_memory(
    data: MemorySearchRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    results = await MemoryService(db).search(
        current_user.id, data.query, agent_id=data.agent_id, top_k=data.top_k
    )
    return MemorySearchResponse(
        results=[MemorySearchResult(memory=entry, score=score) for entry, score in results]
    )


@router.delete("/{memory_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_memory(
    memory_id: uuid.UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    await MemoryService(db).delete_memory(current_user.id, memory_id)

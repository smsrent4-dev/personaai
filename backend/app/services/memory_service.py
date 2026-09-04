"""MemoryService — facts, preferences, events, and conversation
summaries, each embedded for semantic recall.

Kept structurally identical to KnowledgeService's search on purpose
(same top_k_by_similarity helper, same owner/agent scoping pattern) —
memory and knowledge are conceptually the same retrieval problem over
different content, and a future "search everything relevant to this
message" step (Milestone 5) can call both with the same shape.
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.vector_math import top_k_by_similarity
from app.models.memory import MemoryEntry, MemorySource, MemoryType
from app.services.ai import AIProvider, get_ai_provider


class MemoryService:
    def __init__(self, db: AsyncSession, ai_provider: AIProvider | None = None):
        self.db = db
        self.ai_provider = ai_provider or get_ai_provider()

    async def create_memory(
        self,
        owner_id: uuid.UUID,
        memory_type: MemoryType,
        content: str,
        agent_id: uuid.UUID | None = None,
        source: MemorySource = MemorySource.MANUAL,
    ) -> MemoryEntry:
        vector = (await self.ai_provider.embed([content]))[0]
        entry = MemoryEntry(
            owner_id=owner_id,
            agent_id=agent_id,
            memory_type=memory_type,
            source=source,
            content=content,
            embedding=vector,
        )
        self.db.add(entry)
        await self.db.commit()
        await self.db.refresh(entry)
        return entry

    async def list_memories(
        self, owner_id: uuid.UUID, agent_id: uuid.UUID | None = None
    ) -> list[MemoryEntry]:
        stmt = select(MemoryEntry).where(MemoryEntry.owner_id == owner_id)
        if agent_id is not None:
            stmt = stmt.where((MemoryEntry.agent_id == agent_id) | (MemoryEntry.agent_id.is_(None)))
        stmt = stmt.order_by(MemoryEntry.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_memory(self, owner_id: uuid.UUID, memory_id: uuid.UUID) -> MemoryEntry:
        result = await self.db.execute(
            select(MemoryEntry).where(MemoryEntry.id == memory_id, MemoryEntry.owner_id == owner_id)
        )
        entry = result.scalar_one_or_none()
        if entry is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Memory not found")
        return entry

    async def delete_memory(self, owner_id: uuid.UUID, memory_id: uuid.UUID) -> None:
        entry = await self.get_memory(owner_id, memory_id)
        await self.db.delete(entry)
        await self.db.commit()

    async def search(
        self,
        owner_id: uuid.UUID,
        query: str,
        agent_id: uuid.UUID | None = None,
        top_k: int = 5,
    ) -> list[tuple[MemoryEntry, float]]:
        candidates = await self.list_memories(owner_id, agent_id)
        if not candidates:
            return []
        query_vector = (await self.ai_provider.embed([query]))[0]
        return top_k_by_similarity(query_vector, candidates, key=lambda m: m.embedding, k=top_k)

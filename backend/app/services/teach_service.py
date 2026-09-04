"""Teach My AI.

The whole point of this feature is "no prompt editing, no coding, no
manual configuration" — the user types a plain sentence and it becomes
structured memory. The classification step (fact vs preference vs
event) reuses AIProvider.classify() from Milestone 2, the same
mechanism the Router uses to pick an agent — one interface, two
different label sets, no new AI-calling code needed.
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import MemoryEntry, MemorySource, MemoryType
from app.services.ai import AIProvider, get_ai_provider
from app.services.memory_service import MemoryService

_CLASSIFICATION_LABELS = [t.value for t in MemoryType if t != MemoryType.CONVERSATION_SUMMARY]


class TeachService:
    def __init__(self, db: AsyncSession, ai_provider: AIProvider | None = None):
        self.ai_provider = ai_provider or get_ai_provider()
        self.memory_service = MemoryService(db, self.ai_provider)

    async def teach(
        self, owner_id: uuid.UUID, statement: str, agent_id: uuid.UUID | None = None
    ) -> MemoryEntry:
        label = await self.ai_provider.classify(statement, _CLASSIFICATION_LABELS)
        memory_type = MemoryType(label)
        return await self.memory_service.create_memory(
            owner_id=owner_id,
            memory_type=memory_type,
            content=statement,
            agent_id=agent_id,
            source=MemorySource.TEACH,
        )

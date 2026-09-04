"""AnalyticsService - every number here comes from a real aggregate
query against the owner's own data. No simulated metrics, no fake
time series filled in for visual completeness - if there's no data
for a bucket, it's a real zero, not omitted or interpolated.
"""
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentStatus
from app.models.conversation import Conversation
from app.models.knowledge import KnowledgeDocument, KnowledgeStatus
from app.models.message import Message
from app.models.product import Product, ProductStatus


class AnalyticsService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def summary(self, owner_id: uuid.UUID, days: int = 14) -> dict:
        total_conversations = await self._count(select(Conversation).where(Conversation.owner_id == owner_id))
        total_messages = await self._count(select(Message).where(Message.owner_id == owner_id))
        active_agents = await self._count(
            select(Agent).where(Agent.owner_id == owner_id, Agent.status == AgentStatus.ACTIVE)
        )
        knowledge_ready = await self._count(
            select(KnowledgeDocument).where(
                KnowledgeDocument.owner_id == owner_id, KnowledgeDocument.status == KnowledgeStatus.READY
            )
        )
        active_products = await self._count(
            select(Product).where(Product.owner_id == owner_id, Product.status == ProductStatus.ACTIVE)
        )

        return {
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "active_agents": active_agents,
            "knowledge_documents_ready": knowledge_ready,
            "active_products": active_products,
            "messages_per_day": await self.messages_per_day(owner_id, days),
            "messages_by_agent": await self.messages_by_agent(owner_id),
        }

    async def _count(self, stmt) -> int:
        result = await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        return result.scalar_one()

    async def messages_per_day(self, owner_id: uuid.UUID, days: int) -> list[dict]:
        since = datetime.now(timezone.utc) - timedelta(days=days - 1)
        since_midnight = since.replace(hour=0, minute=0, second=0, microsecond=0)

        result = await self.db.execute(
            select(Message.created_at).where(Message.owner_id == owner_id, Message.created_at >= since_midnight)
        )
        counts: dict[str, int] = {}
        for (created_at,) in result.all():
            day_key = created_at.date().isoformat()
            counts[day_key] = counts.get(day_key, 0) + 1

        series = []
        for i in range(days):
            day = (since_midnight + timedelta(days=i)).date().isoformat()
            series.append({"date": day, "count": counts.get(day, 0)})
        return series

    async def messages_by_agent(self, owner_id: uuid.UUID) -> list[dict]:
        result = await self.db.execute(
            select(Agent.id, Agent.name, func.count(Message.id))
            .join(Message, Message.agent_id == Agent.id)
            .where(Agent.owner_id == owner_id)
            .group_by(Agent.id, Agent.name)
            .order_by(func.count(Message.id).desc())
        )
        return [
            {"agent_id": str(agent_id), "agent_name": name, "message_count": count}
            for agent_id, name, count in result.all()
        ]

"""Agent CRUD, scoped to owner_id throughout.

Every query filters on `owner_id == current_user.id` — that's the
entire multi-tenant isolation mechanism for agents. A missing or
mismatched owner_id returns 404 (not 403), so we never confirm to a
caller that an agent ID exists under a different account.
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.plan_limits import enforce_agent_limit
from app.models.agent import Agent
from app.models.user import User
from app.schemas.agent import AgentCreate, AgentUpdate
from app.services.audit_service import AuditService


class AgentService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def list_agents(self, owner_id: uuid.UUID) -> list[Agent]:
        result = await self.db.execute(
            select(Agent).where(Agent.owner_id == owner_id).order_by(Agent.created_at)
        )
        return list(result.scalars().all())

    async def get_agent(self, owner_id: uuid.UUID, agent_id: uuid.UUID) -> Agent:
        result = await self.db.execute(
            select(Agent).where(Agent.id == agent_id, Agent.owner_id == owner_id)
        )
        agent = result.scalar_one_or_none()
        if agent is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Agent not found")
        return agent

    async def create_agent(self, owner: User, data: AgentCreate) -> Agent:
        await enforce_agent_limit(self.db, owner.id)
        agent = Agent(
            owner_id=owner.id,
            name=data.name,
            description=data.description,
            avatar_url=data.avatar_url,
            agent_type=data.agent_type,
            instructions=data.instructions,
            model=data.model or settings.GEMINI_MODEL,
            temperature=data.temperature,
            permissions=data.permissions,
        )
        self.db.add(agent)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def update_agent(self, owner_id: uuid.UUID, agent_id: uuid.UUID, data: AgentUpdate) -> Agent:
        agent = await self.get_agent(owner_id, agent_id)
        for field, value in data.model_dump(exclude_unset=True).items():
            setattr(agent, field, value)
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def delete_agent(self, owner_id: uuid.UUID, agent_id: uuid.UUID) -> None:
        agent = await self.get_agent(owner_id, agent_id)
        agent_name = agent.name
        await self.db.delete(agent)
        await self.db.commit()
        await AuditService(self.db).log(
            action="agent.deleted", user_id=owner_id, resource_type="agent",
            resource_id=str(agent_id), context={"name": agent_name},
        )

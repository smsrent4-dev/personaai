"""Router — decides which of a user's active agents should answer an
incoming message.

This is deliberately NOT hardcoded routing (e.g. "if message contains
'price' -> Sales Agent"). It builds a classification prompt describing
each active agent and hands it to AIProvider.classify(), so routing
quality improves automatically as agent descriptions/instructions get
richer, and works identically regardless of which AI provider is
configured.

Multi-agent collaboration (a message needing two agents) is out of
scope for this milestone — routing picks exactly one agent. Extending
this to "may require collaboration" is a Milestone 5+ concern once
there's an actual conversation/message pipeline to hand off between
agents within.
"""
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent, AgentStatus
from app.services.agent_service import AgentService
from app.services.ai import AIProvider, get_ai_provider


class RouterService:
    def __init__(self, db: AsyncSession, ai_provider: AIProvider | None = None):
        self.db = db
        self.agent_service = AgentService(db)
        self.ai_provider = ai_provider or get_ai_provider()

    async def route(self, owner_id: uuid.UUID, message: str) -> Agent:
        all_agents = await self.agent_service.list_agents(owner_id)
        active_agents = [a for a in all_agents if a.status == AgentStatus.ACTIVE]

        if not active_agents:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="This account has no active agents to route to. Activate at least one agent first.",
            )

        if len(active_agents) == 1:
            return active_agents[0]

        classification_text = self._build_classification_prompt(active_agents, message)
        labels = [agent.name for agent in active_agents]

        chosen_name = await self.ai_provider.classify(classification_text, labels)

        for agent in active_agents:
            if agent.name == chosen_name:
                return agent

        # classify() guarantees a label from `labels` or raises — this is
        # unreachable in practice, but fail loudly rather than silently
        # picking a default agent if that guarantee is ever violated.
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Router received an agent name that doesn't match any active agent.",
        )

    @staticmethod
    def _build_classification_prompt(agents: list[Agent], message: str) -> str:
        agent_lines = "\n".join(
            f"- {agent.name} ({agent.agent_type.value}): {agent.description or 'No description provided.'}"
            for agent in agents
        )
        return (
            "A business has the following AI agents available to respond to incoming messages:\n"
            f"{agent_lines}\n\n"
            f'Incoming message: "{message}"\n\n'
            "Which agent should respond to this message?"
        )

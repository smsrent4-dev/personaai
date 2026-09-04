"""Tool interface - internal PersonaAI actions the AI can invoke via
generate_with_tools() (see app/services/ai/base.py).

Scope note: this is the "Internal PersonaAI actions" category from the
spec's Tools Framework list. REST API tools, webhook tools, SQL query
tools, and sandboxed custom Python tools are NOT implemented - this is
a fixed, curated set of real internal actions (search_product,
create_order), not a generic pluggable framework for arbitrary
external tools. Extending to a true plugin system is real future work,
flagged rather than faked.
"""
import uuid
from abc import ABC, abstractmethod
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.customer import Customer
from app.services.ai.base import ToolDefinition


@dataclass
class ToolContext:
    db: AsyncSession
    owner_id: uuid.UUID
    customer: Customer
    conversation_id: uuid.UUID | None


class Tool(ABC):
    name: str = "tool"
    description: str = ""
    parameters: dict = {"type": "object", "properties": {}, "required": []}

    def definition(self) -> ToolDefinition:
        return ToolDefinition(name=self.name, description=self.description, parameters=self.parameters)

    @abstractmethod
    async def execute(self, arguments: dict, context: ToolContext) -> dict:
        raise NotImplementedError

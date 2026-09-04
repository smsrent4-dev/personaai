from pydantic import BaseModel


class MessagesPerDay(BaseModel):
    date: str
    count: int


class MessagesByAgent(BaseModel):
    agent_id: str
    agent_name: str
    message_count: int


class AnalyticsSummary(BaseModel):
    total_conversations: int
    total_messages: int
    active_agents: int
    knowledge_documents_ready: int
    active_products: int
    messages_per_day: list[MessagesPerDay]
    messages_by_agent: list[MessagesByAgent]

import uuid
from datetime import datetime

from pydantic import BaseModel


class AdminUserRow(BaseModel):
    id: uuid.UUID
    email: str
    full_name: str
    business_name: str | None
    is_active: bool
    is_email_verified: bool
    is_platform_admin: bool
    created_at: datetime
    agent_count: int
    conversation_count: int
    message_count: int


class SignupsPerDay(BaseModel):
    date: str
    count: int


class PlatformStats(BaseModel):
    total_users: int
    active_users: int
    total_agents: int
    total_conversations: int
    total_messages: int
    total_integrations: int
    signups_last_7_days: list[SignupsPerDay]


class RevenuePerDay(BaseModel):
    date: str
    amount: float


class PlanDistributionRow(BaseModel):
    plan_id: uuid.UUID | None
    plan_name: str
    count: int
    percent: float


class RecentTransactionRow(BaseModel):
    id: uuid.UUID
    user_email: str | None
    user_full_name: str | None
    amount: float | None
    currency: str | None
    event_type: str
    processed: bool
    created_at: datetime


class SystemHealth(BaseModel):
    database_ok: bool
    storage_ok: bool
    storage_used_bytes: int | None


class AdminDashboard(BaseModel):
    total_users: int
    active_businesses: int
    monthly_revenue: float
    monthly_revenue_currency: str
    monthly_revenue_change_pct: float | None
    active_agents: int
    revenue_last_7_days: list[RevenuePerDay]
    subscription_distribution: list[PlanDistributionRow]
    recent_users: list[AdminUserRow]
    recent_transactions: list[RecentTransactionRow]
    system_health: SystemHealth

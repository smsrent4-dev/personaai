"""AdminService - platform-wide oversight.

Every other service in this codebase scopes queries by owner_id as its
entire multi-tenant isolation mechanism (see app/services/agent_service.py's
docstring). This service is the deliberate, audited exception: it exists
specifically to look across every account, gated by require_platform_admin
(app/core/deps.py) rather than the normal get_current_active_user check.
Every mutating action here is audit-logged.
"""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import Agent
from app.models.conversation import Conversation
from app.models.integration import PlatformIntegration
from app.models.message import Message
from app.models.platform_bootstrap import PlatformBootstrap
from app.models.user import User
from app.services.audit_service import AuditService


class AdminService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def bootstrap_first_admin(self, current_user: User) -> User:
        """Self-service bootstrap: promotes the calling user to platform
        admin, but ONLY if no platform admin has ever been bootstrapped.
        Further admins must be promoted by an existing admin (see
        promote_user), which is already gated by require_platform_admin
        and so isn't racy the same way — only this very first grant is.

        Race-safety: this claims a single fixed-PK row (PlatformBootstrap,
        id=1) via INSERT before granting anything. Primary-key uniqueness
        is enforced atomically by the database itself, so if two requests
        race, exactly one INSERT succeeds and the other raises
        IntegrityError — unlike the previous "SELECT count(*), then if
        zero, promote" version, which had a window where two concurrent
        callers could both read zero and both get promoted. See
        app/models/platform_bootstrap.py for the full rationale.
        """
        self.db.add(PlatformBootstrap(id=1, admin_user_id=current_user.id))
        try:
            await self.db.flush()
        except IntegrityError:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A platform admin already exists. Ask an existing admin to promote your account.",
            )

        current_user.is_platform_admin = True
        await self.db.commit()
        await self.db.refresh(current_user)
        await AuditService(self.db).log(
            action="platform_admin.bootstrapped", user_id=current_user.id, resource_type="user",
            resource_id=str(current_user.id),
        )
        return current_user

    async def platform_stats(self) -> dict:
        total_users = await self._count(select(User))
        active_users = await self._count(select(User).where(User.is_active.is_(True)))
        total_agents = await self._count(select(Agent))
        total_conversations = await self._count(select(Conversation))
        total_messages = await self._count(select(Message))
        total_integrations = await self._count(select(PlatformIntegration))

        since = datetime.now(timezone.utc) - timedelta(days=6)
        since_midnight = since.replace(hour=0, minute=0, second=0, microsecond=0)
        result = await self.db.execute(select(User.created_at).where(User.created_at >= since_midnight))
        counts: dict[str, int] = {}
        for (created_at,) in result.all():
            key = created_at.date().isoformat()
            counts[key] = counts.get(key, 0) + 1
        signups_last_7_days = []
        for i in range(7):
            day = (since_midnight + timedelta(days=i)).date().isoformat()
            signups_last_7_days.append({"date": day, "count": counts.get(day, 0)})

        return {
            "total_users": total_users,
            "active_users": active_users,
            "total_agents": total_agents,
            "total_conversations": total_conversations,
            "total_messages": total_messages,
            "total_integrations": total_integrations,
            "signups_last_7_days": signups_last_7_days,
        }

    async def _count(self, stmt) -> int:
        result = await self.db.execute(select(func.count()).select_from(stmt.subquery()))
        return result.scalar_one()

    async def platform_dashboard(self) -> dict:
        """Backs the platform-admin Overview page. Every number here is
        computed from real rows — nothing is a placeholder — with one
        deliberate exception noted inline: system_health only reports
        what's actually cheap and honest to check from inside a request
        (DB reachability, real on-disk storage usage for the local
        backend), not a fabricated uptime percentage. A genuine "99.9%
        API uptime" figure needs real historical monitoring data this
        app doesn't collect — showing an invented one would be worse
        than not showing one at all.
        """
        from app.models.agent import AgentStatus
        from app.models.billing_event import BillingEvent
        from app.models.billing_plan import BillingPlan
        from app.models.subscription import Subscription, SubscriptionStatus
        from app.services.knowledge.storage import LocalStorageBackend, get_storage_backend

        total_users = await self._count(select(User))
        active_agents = await self._count(select(Agent).where(Agent.status == AgentStatus.ACTIVE))
        active_businesses = await self._count(
            select(Subscription).where(Subscription.status == SubscriptionStatus.ACTIVE)
        )

        now = datetime.now(timezone.utc)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        prev_month_end = month_start - timedelta(seconds=1)
        prev_month_start = prev_month_end.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        async def _revenue_sum(start: datetime, end: datetime) -> float:
            result = await self.db.execute(
                select(func.coalesce(func.sum(BillingEvent.amount), 0)).where(
                    BillingEvent.event_type == "charge.success",
                    BillingEvent.created_at >= start,
                    BillingEvent.created_at < end,
                )
            )
            return float(result.scalar_one())

        monthly_revenue = await _revenue_sum(month_start, now)
        prev_monthly_revenue = await _revenue_sum(prev_month_start, month_start)
        revenue_change_pct = (
            None
            if prev_monthly_revenue == 0
            else round(((monthly_revenue - prev_monthly_revenue) / prev_monthly_revenue) * 100, 1)
        )

        revenue_last_7_days = []
        for i in range(6, -1, -1):
            day_start = (now - timedelta(days=i)).replace(hour=0, minute=0, second=0, microsecond=0)
            day_end = day_start + timedelta(days=1)
            amount = await _revenue_sum(day_start, day_end)
            revenue_last_7_days.append({"date": day_start.date().isoformat(), "amount": amount})

        dist_result = await self.db.execute(
            select(BillingPlan.id, BillingPlan.name, func.count(Subscription.id))
            .join(Subscription, Subscription.plan_id == BillingPlan.id)
            .where(Subscription.status == SubscriptionStatus.ACTIVE)
            .group_by(BillingPlan.id, BillingPlan.name)
            .order_by(func.count(Subscription.id).desc())
        )
        dist_rows = dist_result.all()
        dist_total = sum(count for _id, _name, count in dist_rows) or 1
        subscription_distribution = [
            {
                "plan_id": plan_id,
                "plan_name": plan_name,
                "count": count,
                "percent": round((count / dist_total) * 100, 1),
            }
            for plan_id, plan_name, count in dist_rows
        ]

        recent_users_raw = await self.list_users(limit=5, offset=0)
        recent_users = [
            {
                "id": row["user"].id,
                "email": row["user"].email,
                "full_name": row["user"].full_name,
                "business_name": row["user"].business_name,
                "is_active": row["user"].is_active,
                "is_email_verified": row["user"].is_email_verified,
                "is_platform_admin": row["user"].is_platform_admin,
                "created_at": row["user"].created_at,
                "agent_count": row["agent_count"],
                "conversation_count": row["conversation_count"],
                "message_count": row["message_count"],
            }
            for row in recent_users_raw
        ]

        tx_result = await self.db.execute(
            select(BillingEvent, User.email, User.full_name)
            .outerjoin(User, User.id == BillingEvent.owner_id)
            .order_by(BillingEvent.created_at.desc())
            .limit(8)
        )
        recent_transactions = [
            {
                "id": event.id,
                "user_email": email,
                "user_full_name": full_name,
                "amount": float(event.amount) if event.amount is not None else None,
                "currency": event.currency,
                "event_type": event.event_type,
                "processed": event.processed,
                "created_at": event.created_at,
            }
            for event, email, full_name in tx_result.all()
        ]

        database_ok = True
        try:
            await self.db.execute(select(1))
        except Exception:
            database_ok = False

        storage_ok = True
        storage_used_bytes: int | None = None
        try:
            backend = get_storage_backend()
            if isinstance(backend, LocalStorageBackend):
                storage_used_bytes = sum(
                    f.stat().st_size for f in backend.base_dir.rglob("*") if f.is_file()
                )
        except Exception:
            storage_ok = False

        return {
            "total_users": total_users,
            "active_businesses": active_businesses,
            "monthly_revenue": monthly_revenue,
            "monthly_revenue_currency": "NGN",
            "monthly_revenue_change_pct": revenue_change_pct,
            "active_agents": active_agents,
            "revenue_last_7_days": revenue_last_7_days,
            "subscription_distribution": subscription_distribution,
            "recent_users": recent_users,
            "recent_transactions": recent_transactions,
            "system_health": {
                "database_ok": database_ok,
                "storage_ok": storage_ok,
                "storage_used_bytes": storage_used_bytes,
            },
        }

    async def list_users(self, search: str | None = None, limit: int = 100, offset: int = 0) -> list[dict]:
        stmt = select(User).order_by(User.created_at.desc()).limit(limit).offset(offset)
        if search:
            like = f"%{search}%"
            stmt = stmt.where((User.email.ilike(like)) | (User.full_name.ilike(like)))
        result = await self.db.execute(stmt)
        users = list(result.scalars().all())

        rows = []
        for user in users:
            agent_count = await self._count(select(Agent).where(Agent.owner_id == user.id))
            conversation_count = await self._count(select(Conversation).where(Conversation.owner_id == user.id))
            message_count = await self._count(select(Message).where(Message.owner_id == user.id))
            rows.append(
                {
                    "user": user,
                    "agent_count": agent_count,
                    "conversation_count": conversation_count,
                    "message_count": message_count,
                }
            )
        return rows

    async def get_user(self, user_id: uuid.UUID) -> User:
        result = await self.db.execute(select(User).where(User.id == user_id))
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
        return user

    async def set_active(self, admin: User, user_id: uuid.UUID, active: bool) -> User:
        user = await self.get_user(user_id)
        if user.id == admin.id and not active:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="You cannot suspend your own account")
        user.is_active = active
        await self.db.commit()
        await self.db.refresh(user)
        await AuditService(self.db).log(
            action="user.suspended" if not active else "user.reactivated",
            user_id=admin.id, resource_type="user", resource_id=str(user.id),
        )
        return user

    async def promote_user(self, admin: User, user_id: uuid.UUID) -> User:
        user = await self.get_user(user_id)
        user.is_platform_admin = True
        await self.db.commit()
        await self.db.refresh(user)
        await AuditService(self.db).log(
            action="platform_admin.promoted", user_id=admin.id, resource_type="user", resource_id=str(user.id),
        )
        return user

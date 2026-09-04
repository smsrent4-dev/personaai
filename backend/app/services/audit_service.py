"""AuditService - writes AuditLog rows. Deliberately fire-and-forget:
a failure to write an audit entry should never break the action being
audited, so callers use `await audit.log(...)` without wrapping it in
extra error handling - write failures are caught and logged here, not
propagated.
"""
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit_log import AuditLog

logger = logging.getLogger(__name__)


class AuditService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def log(
        self,
        action: str,
        user_id: uuid.UUID | None = None,
        resource_type: str | None = None,
        resource_id: str | None = None,
        ip_address: str | None = None,
        context: dict | None = None,
    ) -> None:
        try:
            entry = AuditLog(
                user_id=user_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                ip_address=ip_address,
                context=context or {},
            )
            self.db.add(entry)
            await self.db.commit()
        except Exception:
            logger.error("Failed to write audit log for action '%s'", action, exc_info=True)

    async def list_for_user(self, user_id: uuid.UUID, limit: int = 100) -> list[AuditLog]:
        result = await self.db.execute(
            select(AuditLog).where(AuditLog.user_id == user_id).order_by(AuditLog.created_at.desc()).limit(limit)
        )
        return list(result.scalars().all())

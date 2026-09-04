import uuid

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notification import Notification, NotificationType


class NotificationService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create(
        self,
        owner_id: uuid.UUID,
        type_: NotificationType,
        title: str,
        body: str | None = None,
        context: dict | None = None,
    ) -> Notification:
        notification = Notification(owner_id=owner_id, type=type_, title=title, body=body, context=context or {})
        self.db.add(notification)
        await self.db.flush()
        return notification

    async def list_notifications(self, owner_id: uuid.UUID, unread_only: bool = False) -> list[Notification]:
        stmt = select(Notification).where(Notification.owner_id == owner_id)
        if unread_only:
            stmt = stmt.where(Notification.is_read.is_(False))
        stmt = stmt.order_by(Notification.created_at.desc()).limit(200)
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def unread_count(self, owner_id: uuid.UUID) -> int:
        result = await self.db.execute(
            select(func.count())
            .select_from(Notification)
            .where(Notification.owner_id == owner_id, Notification.is_read.is_(False))
        )
        return result.scalar_one()

    async def mark_read(self, owner_id: uuid.UUID, notification_id: uuid.UUID) -> Notification:
        result = await self.db.execute(
            select(Notification).where(Notification.id == notification_id, Notification.owner_id == owner_id)
        )
        notification = result.scalar_one_or_none()
        if notification is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Notification not found")
        notification.is_read = True
        await self.db.commit()
        await self.db.refresh(notification)
        return notification

    async def mark_all_read(self, owner_id: uuid.UUID) -> None:
        notifications = await self.list_notifications(owner_id, unread_only=True)
        for notification in notifications:
            notification.is_read = True
        await self.db.commit()

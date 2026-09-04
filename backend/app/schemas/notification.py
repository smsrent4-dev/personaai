import uuid
from datetime import datetime

from pydantic import BaseModel

from app.models.notification import NotificationType


class NotificationResponse(BaseModel):
    id: uuid.UUID
    type: NotificationType
    title: str
    body: str | None
    is_read: bool
    context: dict
    created_at: datetime

    model_config = {"from_attributes": True}

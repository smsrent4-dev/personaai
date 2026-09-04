import uuid
from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.services.audit_service import AuditService

router = APIRouter(prefix="/audit-logs", tags=["Audit Log"])


class AuditLogResponse(BaseModel):
    id: uuid.UUID
    action: str
    resource_type: str | None
    resource_id: str | None
    ip_address: str | None
    created_at: datetime

    model_config = {"from_attributes": True}


@router.get("", response_model=list[AuditLogResponse])
async def list_audit_logs(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Every user can see the security-relevant history on their own
    account — logins, integration changes, agent deletions."""
    return await AuditService(db).list_for_user(current_user.id)

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.memory import MemoryResponse, TeachRequest
from app.services.teach_service import TeachService

router = APIRouter(prefix="/teach", tags=["Teach My AI"])


@router.post("", response_model=MemoryResponse)
async def teach(
    data: TeachRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Free-text input becomes structured memory automatically — no
    prompt editing, no manual configuration. E.g. 'My website package
    now costs $650.' is classified and stored without the user
    choosing a category themselves."""
    service = TeachService(db)
    return await service.teach(current_user.id, data.statement, agent_id=data.agent_id)

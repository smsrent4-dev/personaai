from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.agent import AgentResponse
from app.services.router_service import RouterService

router = APIRouter(prefix="/router", tags=["Router"])


class RouteRequest(BaseModel):
    message: str


@router.post("/route", response_model=AgentResponse)
async def route_message(
    data: RouteRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Given a message, returns the agent that would handle it. This is
    what Milestone 5's Telegram integration calls internally before
    generating a reply — exposed here directly so routing quality can
    be verified before any messaging platform is wired up."""
    service = RouterService(db)
    return await service.route(current_user.id, data.message)

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user, require_platform_admin
from app.database import get_db
from app.models.user import User
from app.schemas.admin import AdminDashboard, AdminUserRow, PlatformStats
from app.schemas.auth import UserResponse
from app.services.admin_service import AdminService

router = APIRouter(prefix="/admin", tags=["Admin"])


@router.post("/bootstrap", response_model=UserResponse)
async def bootstrap_first_admin(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Any logged-in user can call this - but it only succeeds once, for
    whoever calls it first. After that, only an existing admin can promote
    someone else (POST /admin/users/{id}/promote)."""
    return await AdminService(db).bootstrap_first_admin(current_user)


@router.get("/stats", response_model=PlatformStats)
async def platform_stats(
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).platform_stats()


@router.get("/dashboard", response_model=AdminDashboard)
async def platform_dashboard(
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    """Backs the platform-admin Overview page (revenue, subscription
    mix, recent signups/transactions, basic system health)."""
    return await AdminService(db).platform_dashboard()


@router.get("/users", response_model=list[AdminUserRow])
async def list_all_users(
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
    _: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    rows = await AdminService(db).list_users(search=search, limit=limit, offset=offset)
    return [
        AdminUserRow(
            id=row["user"].id,
            email=row["user"].email,
            full_name=row["user"].full_name,
            business_name=row["user"].business_name,
            is_active=row["user"].is_active,
            is_email_verified=row["user"].is_email_verified,
            is_platform_admin=row["user"].is_platform_admin,
            created_at=row["user"].created_at,
            agent_count=row["agent_count"],
            conversation_count=row["conversation_count"],
            message_count=row["message_count"],
        )
        for row in rows
    ]


@router.post("/users/{user_id}/suspend", response_model=UserResponse)
async def suspend_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).set_active(admin, user_id, active=False)


@router.post("/users/{user_id}/reactivate", response_model=UserResponse)
async def reactivate_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).set_active(admin, user_id, active=True)


@router.post("/users/{user_id}/promote", response_model=UserResponse)
async def promote_user(
    user_id: uuid.UUID,
    admin: User = Depends(require_platform_admin),
    db: AsyncSession = Depends(get_db),
):
    return await AdminService(db).promote_user(admin, user_id)

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.deps import get_current_active_user
from app.database import get_db
from app.models.user import User
from app.schemas.auth import (
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserResponse,
    VerifyEmailRequest,
)
from app.services.auth_service import AuthService

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(data: RegisterRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    user = await service.register(data)
    return user


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(data: VerifyEmailRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    await service.verify_email(data.token)


@router.post("/login", response_model=TokenResponse)
async def login(data: LoginRequest, request: Request, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    user = await service.authenticate(data.email, data.password)
    return await service.issue_tokens(
        user,
        user_agent=request.headers.get("user-agent"),
        ip=request.client.host if request.client else None,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    return await service.refresh_access_token(data.refresh_token)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(data: RefreshRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    await service.revoke_refresh_token(data.refresh_token)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(data: ForgotPasswordRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    await service.request_password_reset(data.email)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(data: ResetPasswordRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    await service.reset_password(data.token, data.new_password)


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_active_user)):
    return current_user

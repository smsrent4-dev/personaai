"""Auth business logic, kept out of the endpoint layer so it's unit
testable without spinning up FastAPI's request/response cycle."""
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.core.security import JWTError
from app.models.refresh_token import RefreshToken
from app.models.billing_plan import BillingPlan
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.models.verification_token import TokenPurpose, VerificationToken
from app.schemas.auth import RegisterRequest, TokenResponse
from app.services.audit_service import AuditService
from app.services.default_agents import seed_default_agents
from app.services.email_service import email_service


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, data: RegisterRequest) -> User:
        existing = await self.db.execute(select(User).where(User.email == data.email))
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

        user = User(
            email=data.email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            business_name=data.business_name,
        )
        self.db.add(user)
        await self.db.flush()

        trial_plan = await self._get_default_trial_plan()
        if trial_plan is not None:
            self.db.add(
                Subscription(owner_id=user.id, plan_id=trial_plan.id, status=SubscriptionStatus.ACTIVE)
            )
            await self.db.flush()

        await seed_default_agents(self.db, user, max_agents=trial_plan.max_agents if trial_plan else None)
        await self._issue_verification_email(user)

        await self.db.commit()
        await self.db.refresh(user)
        return user

    async def _get_default_trial_plan(self) -> BillingPlan | None:
        """The plan every new signup gets auto-subscribed to — see
        BillingPlan.is_default_trial's docstring. Returns None (not an
        error) if no plan is flagged, or more than one somehow is
        (picks the first deterministically rather than guessing which
        one was "meant"); registration proceeds unsubscribed either
        way, which app/core/plan_limits.py already treats as
        unlimited — a missing trial-plan flag fails open, not closed."""
        result = await self.db.execute(
            select(BillingPlan)
            .where(BillingPlan.is_default_trial.is_(True), BillingPlan.is_active.is_(True))
            .order_by(BillingPlan.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _issue_verification_email(self, user: User) -> None:
        raw_token = generate_opaque_token()
        record = VerificationToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            purpose=TokenPurpose.EMAIL_VERIFICATION,
            expires_at=datetime.now(timezone.utc) + timedelta(hours=24),
        )
        self.db.add(record)
        await self.db.flush()
        await email_service.send_verification_email(user.email, user.full_name, raw_token)

    async def verify_email(self, raw_token: str) -> None:
        record = await self._consume_token(raw_token, TokenPurpose.EMAIL_VERIFICATION)
        result = await self.db.execute(select(User).where(User.id == record.user_id))
        user = result.scalar_one()
        user.is_email_verified = True
        await self.db.commit()

    async def _consume_token(self, raw_token: str, purpose: TokenPurpose) -> VerificationToken:
        token_hash = hash_token(raw_token)
        result = await self.db.execute(
            select(VerificationToken).where(
                VerificationToken.token_hash == token_hash,
                VerificationToken.purpose == purpose,
            )
        )
        record = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if record is None or record.used or record.expires_at < now:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid or expired token")
        record.used = True
        await self.db.flush()
        return record

    async def authenticate(self, email: str, password: str) -> User:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None or not verify_password(password, user.hashed_password):
            await AuditService(self.db).log(
                action="login.failed", user_id=user.id if user else None, context={"email": email}
            )
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect email or password")
        if not user.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled")
        await AuditService(self.db).log(action="login.success", user_id=user.id)
        return user

    async def issue_tokens(self, user: User, user_agent: str | None = None, ip: str | None = None) -> TokenResponse:
        access = create_access_token(user.id)
        refresh = create_refresh_token(user.id)

        payload = decode_token(refresh)
        expires_at = datetime.fromtimestamp(payload["exp"], tz=timezone.utc)

        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh),
                expires_at=expires_at,
                user_agent=user_agent,
                ip_address=ip,
            )
        )
        await self.db.commit()
        return TokenResponse(access_token=access, refresh_token=refresh)

    async def refresh_access_token(self, raw_refresh_token: str) -> TokenResponse:
        try:
            payload = decode_token(raw_refresh_token)
        except JWTError:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

        if payload.get("type") != "refresh":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token type")

        token_hash = hash_token(raw_refresh_token)
        result = await self.db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        record = result.scalar_one_or_none()

        now = datetime.now(timezone.utc)
        if record is None or record.revoked or record.expires_at < now:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Refresh token is invalid or expired")

        # Rotate: revoke the used token and issue a brand new pair.
        record.revoked = True
        await self.db.flush()

        user_result = await self.db.execute(select(User).where(User.id == uuid.UUID(payload["sub"])))
        user = user_result.scalar_one()
        return await self.issue_tokens(user)

    async def revoke_refresh_token(self, raw_refresh_token: str) -> None:
        token_hash = hash_token(raw_refresh_token)
        result = await self.db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        record = result.scalar_one_or_none()
        if record is not None:
            record.revoked = True
            await self.db.commit()

    async def request_password_reset(self, email: str) -> None:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if user is None:
            # Don't leak whether the email exists.
            return
        raw_token = generate_opaque_token()
        self.db.add(
            VerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                purpose=TokenPurpose.PASSWORD_RESET,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        await self.db.commit()
        await email_service.send_password_reset_email(user.email, user.full_name, raw_token)

    async def reset_password(self, raw_token: str, new_password: str) -> None:
        record = await self._consume_token(raw_token, TokenPurpose.PASSWORD_RESET)
        result = await self.db.execute(select(User).where(User.id == record.user_id))
        user = result.scalar_one()
        user.hashed_password = hash_password(new_password)
        await self.db.commit()

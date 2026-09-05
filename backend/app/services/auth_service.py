"""Authentication business logic.
Authentication logic is kept out of the endpoint layer so it remains
unit-testable without spinning up FastAPI's request/response cycle.
Responsibilities:
- User registration
- Default trial subscription
- Default agent provisioning
- Email verification
- Login/authentication
- Access/refresh token issuance
- Refresh-token rotation
- Refresh-token revocation
- Password reset
External email delivery is intentionally separated from database commits.
A temporary SMTP failure must never prevent a user account from being created.
"""
import logging
import uuid
from datetime import datetime, timedelta, timezone
from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.security import (
    JWTError,
    create_access_token,
    create_refresh_token,
    decode_token,
    generate_opaque_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.billing_plan import BillingPlan
from app.models.refresh_token import RefreshToken
from app.models.subscription import Subscription, SubscriptionStatus
from app.models.user import User
from app.models.verification_token import TokenPurpose, VerificationToken
from app.schemas.auth import RegisterRequest, TokenResponse
from app.services.audit_service import AuditService
from app.services.default_agents import seed_default_agents
from app.services.email_service import email_service
logger = logging.getLogger(__name__)
class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db
    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------
    async def register(self, data: RegisterRequest) -> User:
        """Register a new user.
        The database transaction is committed before attempting to send
        the verification email.
        This is important because SMTP is an external service. If Gmail,
        Resend, or another mail provider is temporarily unavailable, the
        user account should still be created successfully.
        """
        email = data.email.strip().lower()
        # --------------------------------------------------------------
        # Check for existing account
        # --------------------------------------------------------------
        existing = await self.db.execute(
            select(User).where(User.email == email)
        )
        if existing.scalar_one_or_none() is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Email already registered",
            )
        # --------------------------------------------------------------
        # Create user
        # --------------------------------------------------------------
        user = User(
            email=email,
            hashed_password=hash_password(data.password),
            full_name=data.full_name,
            business_name=data.business_name,
        )
        self.db.add(user)
        await self.db.flush()
        # --------------------------------------------------------------
        # Assign default trial subscription
        # --------------------------------------------------------------
        trial_plan = await self._get_default_trial_plan()
        if trial_plan is not None:
            self.db.add(
                Subscription(
                    owner_id=user.id,
                    plan_id=trial_plan.id,
                    status=SubscriptionStatus.ACTIVE,
                )
            )
            await self.db.flush()
        # --------------------------------------------------------------
        # Create default AI agents
        # --------------------------------------------------------------
        await seed_default_agents(
            self.db,
            user,
            max_agents=(
                trial_plan.max_agents
                if trial_plan is not None
                else None
            ),
        )
        # --------------------------------------------------------------
        # Create email verification token
        # --------------------------------------------------------------
        raw_token = await self._create_verification_token(user)
        # --------------------------------------------------------------
        # Commit the account BEFORE external email delivery.
        # --------------------------------------------------------------
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        await self.db.refresh(user)
        # --------------------------------------------------------------
        # Send verification email AFTER successful database commit.
        #
        # EmailService returns False when SMTP is unavailable instead
        # of raising an exception, so registration remains successful.
        # --------------------------------------------------------------
        try:
            sent = await email_service.send_verification_email(
                user.email,
                user.full_name,
                raw_token,
            )
            if not sent:
                logger.warning(
                    "User %s registered successfully, but verification "
                    "email could not be delivered.",
                    user.id,
                )
        except Exception:
            # Defensive protection in case the email service ever changes
            # and unexpectedly raises an exception.
            logger.exception(
                "Unexpected error while sending verification email "
                "for user %s.",
                user.id,
            )
        return user
    # ------------------------------------------------------------------
    # Trial plan
    # ------------------------------------------------------------------
    async def _get_default_trial_plan(self) -> BillingPlan | None:
        """Return the default active trial billing plan.
        If no default trial plan exists, registration proceeds without
        a subscription. This preserves the existing fail-open behavior
        expected by the application's plan-limit logic.
        """
        result = await self.db.execute(
            select(BillingPlan)
            .where(
                BillingPlan.is_default_trial.is_(True),
                BillingPlan.is_active.is_(True),
            )
            .order_by(BillingPlan.created_at)
            .limit(1)
        )
        return result.scalar_one_or_none()
    # ------------------------------------------------------------------
    # Email verification
    # ------------------------------------------------------------------
    async def _create_verification_token(self, user: User) -> str:
        """Create and persist an email verification token.
        Only the hash is stored in the database. The raw token is sent
        to the user's email and is never persisted directly.
        """
        raw_token = generate_opaque_token()
        record = VerificationToken(
            user_id=user.id,
            token_hash=hash_token(raw_token),
            purpose=TokenPurpose.EMAIL_VERIFICATION,
            expires_at=(
                datetime.now(timezone.utc)
                + timedelta(hours=24)
            ),
        )
        self.db.add(record)
        await self.db.flush()
        return raw_token
    async def _issue_verification_email(self, user: User) -> None:
        """Create a verification token and attempt email delivery.
        Kept as a separate helper for compatibility with existing code
        that may call this method internally.
        """
        raw_token = await self._create_verification_token(user)
        try:
            sent = await email_service.send_verification_email(
                user.email,
                user.full_name,
                raw_token,
            )
            if not sent:
                logger.warning(
                    "Verification email was not delivered to %s.",
                    user.email,
                )
        except Exception:
            logger.exception(
                "Unexpected error sending verification email to %s.",
                user.email,
            )
    async def verify_email(self, raw_token: str) -> None:
        """Verify a user's email address using a valid token."""
        record = await self._consume_token(
            raw_token,
            TokenPurpose.EMAIL_VERIFICATION,
        )
        result = await self.db.execute(
            select(User).where(User.id == record.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        user.is_email_verified = True
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
    async def _consume_token(
        self,
        raw_token: str,
        purpose: TokenPurpose,
    ) -> VerificationToken:
        """Validate and consume a verification/reset token."""
        if not raw_token or not raw_token.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired token",
            )
        token_hash = hash_token(raw_token.strip())
        result = await self.db.execute(
            select(VerificationToken).where(
                VerificationToken.token_hash == token_hash,
                VerificationToken.purpose == purpose,
            )
        )
        record = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if (
            record is None
            or record.used
            or record.expires_at < now
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid or expired token",
            )
        record.used = True
        await self.db.flush()
        return record
    # ------------------------------------------------------------------
    # Authentication / Login
    # ------------------------------------------------------------------
    async def authenticate(
        self,
        email: str,
        password: str,
    ) -> User:
        """Authenticate a user using email and password."""
        email = email.strip().lower()
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        # Do not reveal whether the email exists.
        if user is None or not verify_password(
            password,
            user.hashed_password,
        ):
            await AuditService(self.db).log(
                action="login.failed",
                user_id=user.id if user else None,
                context={"email": email},
            )
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )
        await AuditService(self.db).log(
            action="login.success",
            user_id=user.id,
        )
        return user
    # ------------------------------------------------------------------
    # JWT tokens
    # ------------------------------------------------------------------
    async def issue_tokens(
        self,
        user: User,
        user_agent: str | None = None,
        ip: str | None = None,
    ) -> TokenResponse:
        """Issue access and refresh tokens for a user."""
        access = create_access_token(user.id)
        refresh = create_refresh_token(user.id)
        payload = decode_token(refresh)
        expires_at = datetime.fromtimestamp(
            payload["exp"],
            tz=timezone.utc,
        )
        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh),
                expires_at=expires_at,
                user_agent=user_agent,
                ip_address=ip,
            )
        )
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        return TokenResponse(
            access_token=access,
            refresh_token=refresh,
        )
    # ------------------------------------------------------------------
    # Refresh token
    # ------------------------------------------------------------------
    async def refresh_access_token(
        self,
        raw_refresh_token: str,
    ) -> TokenResponse:
        """Rotate a refresh token and issue a new token pair."""
        try:
            payload = decode_token(raw_refresh_token)
        except JWTError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        if payload.get("type") != "refresh":
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid token type",
            )
        subject = payload.get("sub")
        if not subject:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        try:
            user_id = uuid.UUID(subject)
        except (ValueError, TypeError):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid refresh token",
            )
        token_hash = hash_token(raw_refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash
            )
        )
        record = result.scalar_one_or_none()
        now = datetime.now(timezone.utc)
        if (
            record is None
            or record.revoked
            or record.expires_at < now
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Refresh token is invalid or expired",
            )
        # --------------------------------------------------------------
        # Rotate refresh token.
        # --------------------------------------------------------------
        record.revoked = True
        await self.db.flush()
        user_result = await self.db.execute(
            select(User).where(User.id == user_id)
        )
        user = user_result.scalar_one_or_none()
        if user is None:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="User no longer exists",
            )
        if not user.is_active:
            await self.db.rollback()
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Account is disabled",
            )
        # issue_tokens() commits the transaction containing the revoked
        # old token and the newly-created refresh token.
        return await self.issue_tokens(user)
    # ------------------------------------------------------------------
    # Revoke refresh token
    # ------------------------------------------------------------------
    async def revoke_refresh_token(
        self,
        raw_refresh_token: str,
    ) -> None:
        """Revoke a refresh token if it exists."""
        if not raw_refresh_token:
            return
        token_hash = hash_token(raw_refresh_token)
        result = await self.db.execute(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash
            )
        )
        record = result.scalar_one_or_none()
        if record is not None and not record.revoked:
            record.revoked = True
            try:
                await self.db.commit()
            except Exception:
                await self.db.rollback()
                raise
    # ------------------------------------------------------------------
    # Password reset
    # ------------------------------------------------------------------
    async def request_password_reset(
        self,
        email: str,
    ) -> None:
        """Create a password-reset token and send the reset email.
        The method intentionally does not reveal whether an account
        exists for the supplied email address.
        """
        email = email.strip().lower()
        result = await self.db.execute(
            select(User).where(User.email == email)
        )
        user = result.scalar_one_or_none()
        if user is None:
            # Do not leak whether the email exists.
            return
        raw_token = generate_opaque_token()
        self.db.add(
            VerificationToken(
                user_id=user.id,
                token_hash=hash_token(raw_token),
                purpose=TokenPurpose.PASSWORD_RESET,
                expires_at=(
                    datetime.now(timezone.utc)
                    + timedelta(hours=1)
                ),
            )
        )
        # Persist the reset token before attempting external email
        # delivery.
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
        # SMTP failure must not turn an otherwise valid password-reset
        # request into a server error.
        try:
            sent = await email_service.send_password_reset_email(
                user.email,
                user.full_name,
                raw_token,
            )
            if not sent:
                logger.warning(
                    "Password reset token created for %s, but the "
                    "email could not be delivered.",
                    user.email,
                )
        except Exception:
            logger.exception(
                "Unexpected error sending password reset email "
                "to %s.",
                user.email,
            )
    async def reset_password(
        self,
        raw_token: str,
        new_password: str,
    ) -> None:
        """Reset a user's password using a valid reset token."""
        record = await self._consume_token(
            raw_token,
            TokenPurpose.PASSWORD_RESET,
        )
        result = await self.db.execute(
            select(User).where(User.id == record.user_id)
        )
        user = result.scalar_one_or_none()
        if user is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found",
            )
        user.hashed_password = hash_password(new_password)
        try:
            await self.db.commit()
        except Exception:
            await self.db.rollback()
            raise
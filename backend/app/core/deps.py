"""Shared FastAPI dependencies.

Authentication:
- get_current_user()
- get_current_active_user()

Authorization:
- require_role()
- require_platform_admin()

Subscription:
- require_active_subscription()

IMPORTANT:
Authentication and subscription access are intentionally separate.

A user can be authenticated without having an active subscription.

Billing endpoints should continue using get_current_active_user()
so users with incomplete, canceled, past-due, or missing subscriptions
can still access billing and complete payment.

Endpoints that actually require an active PersonaAI subscription should
explicitly depend on require_active_subscription().
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import JWTError, decode_token
from app.core.subscription_access import check_subscription_access
from app.database import get_db
from app.models.subscription import SubscriptionStatus
from app.models.user import User, UserRole


oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/auth/login"
)


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Resolve the authenticated user from the access token."""

    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_token(token)

        if payload.get("type") != "access":
            raise credentials_error

        user_id = payload.get("sub")

        if user_id is None:
            raise credentials_error

        try:
            parsed_user_id = uuid.UUID(str(user_id))
        except (ValueError, TypeError):
            raise credentials_error

    except JWTError:
        raise credentials_error

    result = await db.execute(
        select(User).where(
            User.id == parsed_user_id
        )
    )

    user = result.scalar_one_or_none()

    if user is None:
        raise credentials_error

    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    """Require a valid authenticated and active user."""

    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Inactive user account",
        )

    return current_user


async def require_active_subscription(
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require the user to have a currently usable subscription.

    Subscription access is centralized in
    app.core.subscription_access.check_subscription_access().

    Allowed:
        - ACTIVE subscription
        - subscription period has not expired
        - associated billing plan still exists and is active

    Rejected:
        - no subscription
        - incomplete
        - past_due
        - canceled
        - expired subscription period
        - missing/inactive billing plan

    Billing endpoints should NOT use this dependency because users
    with inactive subscriptions must still be able to access billing
    and complete payment.
    """

    (
        allowed,
        subscription,
        plan,
    ) = await check_subscription_access(
        db,
        current_user.id,
    )

    if allowed:
        return current_user

    # No subscription at all.
    if subscription is None:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_required",
                "message": (
                    "An active subscription is required "
                    "to use this feature."
                ),
            },
        )

    # Subscription exists but is not active.
    if subscription.status == SubscriptionStatus.INCOMPLETE:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_incomplete",
                "status": subscription.status.value,
                "message": (
                    "Your payment has not been completed. "
                    "Complete checkout to use this feature."
                ),
            },
        )

    if subscription.status == SubscriptionStatus.PAST_DUE:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_past_due",
                "status": subscription.status.value,
                "message": (
                    "Your subscription payment is past due. "
                    "Please update your payment method."
                ),
            },
        )

    if subscription.status == SubscriptionStatus.CANCELED:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_canceled",
                "status": subscription.status.value,
                "message": (
                    "Your subscription has been canceled. "
                    "Choose a plan to continue."
                ),
            },
        )

    # Covers an ACTIVE subscription whose period has expired,
    # or an ACTIVE subscription whose plan is missing/inactive.
    raise HTTPException(
        status_code=status.HTTP_402_PAYMENT_REQUIRED,
        detail={
            "code": "subscription_inactive",
            "status": subscription.status.value,
            "message": (
                "Your subscription is no longer active. "
                "Please choose a plan or renew your subscription "
                "to continue."
            ),
        },
    )


def require_role(*allowed_roles: UserRole):
    """Dependency factory.

    Example:

        current_user: User = Depends(
            require_role(UserRole.OWNER, UserRole.ADMIN)
        )
    """

    async def checker(
        current_user: User = Depends(get_current_active_user),
    ) -> User:
        if current_user.role not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=(
                    "You do not have permission to perform "
                    "this action"
                ),
            )

        return current_user

    return checker


async def require_platform_admin(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Gate the platform-wide PersonaAI admin panel.

    This is separate from require_role().

    require_role()
        Account-level permissions inside one business.

    require_platform_admin()
        Platform-level PersonaAI administration.
    """

    if not current_user.is_platform_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Platform admin access required",
        )

    return current_user

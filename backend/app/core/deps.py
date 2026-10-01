"""Shared FastAPI dependencies.

Authentication:
- get_current_user()
- get_current_active_user()

Authorization:
- require_role()
- require_platform_admin()

Billing:
- require_active_subscription()

IMPORTANT:
Authentication and subscription access are intentionally separate.

A user can be authenticated without having an active paid subscription.
Paid endpoints must explicitly depend on require_active_subscription()
so an incomplete, canceled, or past-due subscription cannot use paid
features.
"""

import uuid

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import JWTError, decode_token
from app.database import get_db
from app.models.subscription import Subscription, SubscriptionStatus
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
        select(User).where(User.id == parsed_user_id)
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
    """Require the user to have an ACTIVE subscription.

    This dependency is for endpoints that require an active PersonaAI
    subscription.

    IMPORTANT:
    An authenticated user is NOT automatically considered subscribed.

    Allowed:
        SubscriptionStatus.ACTIVE

    Rejected:
        - no subscription
        - incomplete
        - past_due
        - canceled

    This check happens on the backend, so hiding buttons in the frontend
    is not sufficient to bypass it.
    """

    result = await db.execute(
        select(Subscription).where(
            Subscription.owner_id == current_user.id
        )
    )

    subscription = result.scalar_one_or_none()

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

    if subscription.status != SubscriptionStatus.ACTIVE:
        status_messages = {
            SubscriptionStatus.INCOMPLETE: (
                "Your payment has not been completed. "
                "Complete checkout to use this feature."
            ),
            SubscriptionStatus.PAST_DUE: (
                "Your subscription payment is past due. "
                "Please update your payment method."
            ),
            SubscriptionStatus.CANCELED: (
                "Your subscription has been canceled. "
                "Choose a plan to continue."
            ),
        }

        message = status_messages.get(
            subscription.status,
            "An active subscription is required to use this feature.",
        )

        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail={
                "code": "subscription_inactive",
                "status": subscription.status.value,
                "message": message,
            },
        )

    return current_user


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

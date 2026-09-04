"""Password hashing and JWT token utilities.

Access tokens are stateless JWTs (short-lived). Refresh tokens are
also JWTs but their hash is additionally persisted in the
`refresh_tokens` table so individual sessions can be revoked
(see app/models/refresh_token.py).
"""

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.config import settings


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------

# Keep bcrypt because existing users in the database have bcrypt hashes.
#
# requirements.txt:
#   passlib[bcrypt]==1.7.4
#   bcrypt==4.0.1
#
# bcrypt 4.0.1 is intentionally pinned for compatibility with Passlib 1.7.4.
pwd_context = CryptContext(
    schemes=["bcrypt"],
    deprecated="auto",
)


def hash_password(password: str) -> str:
    """Hash a plain-text password using bcrypt."""
    return pwd_context.hash(password)


def verify_password(
    plain_password: str,
    hashed_password: str,
) -> bool:
    """Verify a plain-text password against a stored bcrypt hash.

    Returns False instead of crashing the authentication request if the
    password/hash cannot be verified.
    """
    try:
        return pwd_context.verify(
            plain_password,
            hashed_password,
        )
    except (ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# JWT tokens
# ---------------------------------------------------------------------------

TokenType = Literal["access", "refresh"]


def _create_token(
    subject: str,
    token_type: TokenType,
    expires_delta: timedelta,
) -> str:
    """Create a signed JWT access or refresh token."""
    now = datetime.now(timezone.utc)

    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }

    return jwt.encode(
        payload,
        settings.SECRET_KEY,
        algorithm=settings.ALGORITHM,
    )


def create_access_token(user_id: uuid.UUID) -> str:
    """Create a short-lived access token."""
    return _create_token(
        str(user_id),
        "access",
        timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        ),
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    """Create a long-lived refresh token."""
    return _create_token(
        str(user_id),
        "refresh",
        timedelta(
            days=settings.REFRESH_TOKEN_EXPIRE_DAYS
        ),
    )


def decode_token(token: str) -> dict:
    """Decode and validate a JWT.

    Raises jose.JWTError if the token is invalid or expired.
    Callers are responsible for catching JWTError.
    """
    return jwt.decode(
        token,
        settings.SECRET_KEY,
        algorithms=[settings.ALGORITHM],
    )


# ---------------------------------------------------------------------------
# Token hashing
# ---------------------------------------------------------------------------

def hash_token(token: str) -> str:
    """Return a SHA-256 hash of a refresh/verification token.

    Raw tokens are never stored in the database.
    """
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def generate_opaque_token() -> str:
    """Generate a secure single-use token.

    Used for email verification and password-reset links.
    These are opaque tokens, not JWTs.
    """
    return secrets.token_urlsafe(32)


__all__ = [
    "JWTError",
    "hash_password",
    "verify_password",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_token",
    "generate_opaque_token",
]
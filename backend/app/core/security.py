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

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

TokenType = Literal["access", "refresh"]


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)


def _create_token(subject: str, token_type: TokenType, expires_delta: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": subject,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def create_access_token(user_id: uuid.UUID) -> str:
    return _create_token(
        str(user_id), "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: uuid.UUID) -> str:
    return _create_token(
        str(user_id), "refresh", timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS)
    )


def decode_token(token: str) -> dict:
    """Raises jose.JWTError if invalid/expired — callers must catch it."""
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


def hash_token(token: str) -> str:
    """We only ever store a SHA-256 hash of refresh/verification tokens,
    never the raw token, so a DB leak doesn't hand out valid sessions."""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def generate_opaque_token() -> str:
    """Used for email-verification / password-reset links (not JWTs,
    since these are single-use and looked up by hash, not decoded)."""
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

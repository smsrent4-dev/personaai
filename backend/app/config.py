"""Centralized application configuration.

All environment-driven settings live here so the rest of the codebase
never reads `os.environ` directly. This keeps configuration testable
and makes it trivial to see every knob the platform exposes.
"""
from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # App
    APP_NAME: str = "PersonaAI"
    APP_ENV: str = "development"
    DEBUG: bool = True
    API_V1_PREFIX: str = "/api/v1"

    # Security
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # Database
    DATABASE_URL: str
    DATABASE_URL_SYNC: str
    POSTGRES_USER: str = "personaai"
    POSTGRES_PASSWORD: str = "personaai"
    POSTGRES_DB: str = "personaai"

    # Redis / Celery
    REDIS_URL: str = "redis://redis:6379/0"

    # When True, dispatch_incoming_message() (app/worker.py) runs the
    # messaging pipeline inline using the caller's own DB session
    # instead of enqueueing a Celery task. Production should leave this
    # False — see app/worker.py's module docstring for why backgrounding
    # is the whole point. Tests force this True (tests/conftest.py) so
    # the existing test suite keeps exercising the real pipeline logic
    # against its isolated per-test database, rather than either hitting
    # a real Celery worker/session (Celery tasks open their own
    # AsyncSessionLocal, which wouldn't be the test's swapped-in
    # in-memory DB) or a broker that isn't running in CI.
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # Email
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USER: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM: str = "PersonaAI <no-reply@example.com>"
    SMTP_TLS: bool = True

    FRONTEND_URL: str = "http://localhost:5173"
    # Must be a publicly reachable HTTPS URL in production — Telegram (and
    # every other platform webhook) will not call localhost. Use ngrok or
    # similar for local development.
    API_BASE_URL: str = "http://localhost:8000"

    # AI providers
    AI_DEFAULT_PROVIDER: str = "gemini"
    GEMINI_API_KEY: str = ""
    # This has now gone stale TWICE in the time this project has existed:
    # gemini-2.0-flash (shut down June 1, 2026), then gemini-2.5-flash
    # (retired for new users by ~August 19, 2026, per Google's own API
    # error: "This model models/gemini-2.5-flash is no longer available
    # to new users"). Google shipped gemini-3.6-flash July 21, 2026 and
    # gemini-3.7-flash August 13, 2026 — three weeks apart. At this
    # release cadence, whatever's set here WILL go stale again, probably
    # within weeks, not months. If AI calls start failing with a "model
    # not found"/404 error despite a valid GEMINI_API_KEY, that's what's
    # happening — check https://ai.google.dev/gemini-api/docs/models for
    # the current lineup before assuming the key itself is the problem.
    # A more durable fix than keep patching this string here: switch to
    # settings.GEMINI_MODEL = "gemini-flash-latest", Google's floating
    # alias that always points at their current recommended Flash model
    # (trades a small amount of behavioral stability for never landing on
    # a dead model ID again) — not switched to automatically here since
    # that's a real behavior-versioning tradeoff worth deciding
    # deliberately, not sneaking into an unrelated bug fix.
    GEMINI_MODEL: str = "gemini-3.6-flash"
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"
    # text-embedding-004 outputs 768-dim vectors. If you switch embedding
    # models/providers, update this to match — pgvector columns are fixed-width.
    EMBEDDING_DIMENSIONS: int = 768

    # Knowledge base file storage
    STORAGE_BACKEND: str = "local"
    STORAGE_DIR: str = "./storage"
    MAX_UPLOAD_SIZE_MB: int = 25

    # Telegram (Milestone 5): bot tokens are stored per-user in
    # PlatformIntegration, not globally — each user connects their own bot.

    # WhatsApp Cloud API (Milestone 8). Two connection paths share these
    # settings: Embedded Signup (Meta OAuth — needs META_APP_ID/SECRET/
    # CONFIG_ID) and manual Cloud API setup (per-integration credentials,
    # no app-level config needed beyond the webhook signature secret).
    META_APP_ID: str = ""
    META_APP_SECRET: str = ""
    # Embedded Signup config ID from Meta App Dashboard > WhatsApp > Embedded
    # Signup — identifies which signup flow/permissions to present.
    META_CONFIG_ID: str = ""
    META_GRAPH_API_VERSION: str = "v25.0"
    META_OAUTH_REDIRECT_URI: str = "http://localhost:5173/integrations/whatsapp/callback"
    # Meta's WhatsApp webhook is registered ONCE per Meta App (in the App
    # dashboard), not per connected business — unlike Telegram, where each
    # bot gets its own webhook URL. This is the "Verify Token" you'd put in
    # that one App-level webhook config; per-integration verify tokens
    # (set during manual connect) are also honored as a fallback so the
    # manual-setup flow's "Verify Token" field is genuinely functional.
    WHATSAPP_APP_VERIFY_TOKEN: str = ""

    # Billing (Paystack)
    PAYSTACK_SECRET_KEY: str = ""
    PAYSTACK_PUBLIC_KEY: str = ""
    DEFAULT_BILLING_CURRENCY: str = "NGN"

    # CORS
    CORS_ORIGINS: List[str] = ["http://localhost:5173", "http://localhost:3000"]


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor — import and call this, never instantiate Settings() directly."""
    return Settings()


settings = get_settings()

"""Centralized application configuration.

All environment-driven settings live here so the rest of the codebase
never reads os.environ directly.

This keeps configuration:
- Centralized
- Testable
- Easy to deploy
- Compatible with local .env files
- Compatible with Railway/Render environment variables
"""

from functools import lru_cache
from typing import List

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=True,
    )

    # =========================================================================
    # APPLICATION
    # =========================================================================

    APP_NAME: str = "PersonaAI"

    APP_ENV: str = "development"

    DEBUG: bool = True

    API_V1_PREFIX: str = "/api/v1"

    # =========================================================================
    # SECURITY
    # =========================================================================

    SECRET_KEY: str

    ALGORITHM: str = "HS256"

    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30

    REFRESH_TOKEN_EXPIRE_DAYS: int = 30

    # =========================================================================
    # DATABASE
    # =========================================================================

    DATABASE_URL: str

    DATABASE_URL_SYNC: str

    # Local PostgreSQL defaults.
    #
    # These are mainly useful for local Docker development.
    # Production deployments should provide DATABASE_URL and
    # DATABASE_URL_SYNC through environment variables.
    POSTGRES_USER: str = "personaai"

    POSTGRES_PASSWORD: str = "personaai"

    POSTGRES_DB: str = "personaai"

    # =========================================================================
    # REDIS / CELERY
    # =========================================================================

    REDIS_URL: str = "redis://redis:6379/0"

    # Production:
    #     false
    #
    # Tests:
    #     tests/conftest.py can override this to true.
    #
    # When false, incoming messages are sent to Celery instead of being
    # executed inside the API request process.
    CELERY_TASK_ALWAYS_EAGER: bool = False

    # =========================================================================
    # EMAIL
    # =========================================================================

    SMTP_HOST: str = ""

    SMTP_PORT: int = 587

    SMTP_USER: str = ""

    SMTP_PASSWORD: str = ""

    SMTP_FROM: str = "PersonaAI <no-reply@example.com>"

    SMTP_TLS: bool = True

    # =========================================================================
    # FRONTEND / API URLS
    # =========================================================================

    # Frontend URL used for redirects, CORS-related logic, OAuth callbacks,
    # and other server-side URL generation.
    FRONTEND_URL: str = "http://localhost:5173"

    # Public backend URL.
    #
    # In production this should be the publicly reachable HTTPS URL of
    # the PersonaAI backend.
    #
    # Example:
    # https://your-backend-domain.com
    API_BASE_URL: str = "http://localhost:8000"

    # =========================================================================
    # AI PROVIDERS
    # =========================================================================

    AI_DEFAULT_PROVIDER: str = "gemini"

    # Gemini API key.
    #
    # Production:
    # Set GEMINI_API_KEY in Railway/Render environment variables.
    GEMINI_API_KEY: str = ""

    # Primary Gemini generation model.
    #
    # This can be overridden without changing the source code:
    #
    # GEMINI_MODEL=...
    #
    # Keep this environment-driven in production because Google can
    # retire or replace model IDs over time.
    GEMINI_MODEL: str = "gemini-3.6-flash"

    # Optional fallback Gemini generation model.
    #
    # Leave empty if no verified fallback model is configured.
    #
    # Example:
    # GEMINI_FALLBACK_MODEL=some-supported-model
    #
    # The Gemini provider will only use this after the primary model
    # experiences a retryable service failure.
    GEMINI_FALLBACK_MODEL: str = ""

    # Gemini embedding model.
    #
    # The current PersonaAI vector database schema uses 768 dimensions.
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # Must match the pgvector column dimension used by PersonaAI.
    EMBEDDING_DIMENSIONS: int = 768

    # =========================================================================
    # KNOWLEDGE BASE / FILE STORAGE
    # =========================================================================

    STORAGE_BACKEND: str = "local"

    STORAGE_DIR: str = "./storage"

    MAX_UPLOAD_SIZE_MB: int = 25

    # =========================================================================
    # TELEGRAM
    # =========================================================================
    #
    # Telegram bot tokens are stored per user/integration rather than as a
    # single global application setting.
    #
    # Therefore there is intentionally no global TELEGRAM_BOT_TOKEN here.

    # =========================================================================
    # WHATSAPP CLOUD API / META
    # =========================================================================

    # Meta application credentials used by WhatsApp Embedded Signup.
    META_APP_ID: str = ""

    META_APP_SECRET: str = ""

    # Embedded Signup configuration ID.
    META_CONFIG_ID: str = ""

    # Meta Graph API version.
    META_GRAPH_API_VERSION: str = "v25.0"

    # OAuth callback URL used by the frontend/backend WhatsApp connection
    # flow.
    META_OAUTH_REDIRECT_URI: str = (
        "http://localhost:5173/integrations/whatsapp/callback"
    )

    # Meta WhatsApp webhook verification token.
    #
    # This is configured at the Meta App webhook level.
    WHATSAPP_APP_VERIFY_TOKEN: str = ""

    # =========================================================================
    # BILLING / PAYSTACK
    # =========================================================================

    PAYSTACK_SECRET_KEY: str = ""

    PAYSTACK_PUBLIC_KEY: str = ""

    DEFAULT_BILLING_CURRENCY: str = "NGN"

    # =========================================================================
    # CORS
    # =========================================================================

    # Local-development defaults.
    #
    # In production, override this environment variable with the actual
    # frontend origin(s).
    #
    # Pydantic can parse JSON such as:
    #
    # CORS_ORIGINS=["https://your-frontend.com"]
    #
    # or a JSON string in an environment variable:
    #
    # CORS_ORIGINS='["https://your-frontend.com"]'
    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()


settings = get_settings()

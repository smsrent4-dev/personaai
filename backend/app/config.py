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

    POSTGRES_USER: str = "personaai"

    POSTGRES_PASSWORD: str = "personaai"

    POSTGRES_DB: str = "personaai"

    # =========================================================================
    # REDIS / CELERY
    # =========================================================================

    REDIS_URL: str = "redis://redis:6379/0"

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

    FRONTEND_URL: str = "http://localhost:5173"

    API_BASE_URL: str = "http://localhost:8000"

    # =========================================================================
    # AI PROVIDERS
    # =========================================================================

    AI_DEFAULT_PROVIDER: str = "gemini"

    # Gemini API key.
    #
    # Production:
    # Configure GEMINI_API_KEY in Railway/Render environment variables.
    GEMINI_API_KEY: str = ""

    # Primary Gemini generation model.
    GEMINI_MODEL: str = "gemini-3.6-flash"

    # Optional fallback Gemini generation model.
    GEMINI_FALLBACK_MODEL: str = ""

    # Gemini embedding model.
    GEMINI_EMBEDDING_MODEL: str = "gemini-embedding-001"

    # Must match the pgvector column dimension.
    EMBEDDING_DIMENSIONS: int = 768

    # =========================================================================
    # KNOWLEDGE BASE / FILE STORAGE
    # =========================================================================

    # Supported:
    #
    # local
    # cloudinary
    #
    # Development can use:
    # STORAGE_BACKEND=local
    #
    # Production should use:
    # STORAGE_BACKEND=cloudinary
    STORAGE_BACKEND: str = "local"

    # Used by LocalStorageBackend.
    STORAGE_DIR: str = "./storage"

    # Maximum application-level upload size.
    #
    # Product images currently have their own 10 MB limit in
    # ProductService.
    MAX_UPLOAD_SIZE_MB: int = 25

    # -------------------------------------------------------------------------
    # CLOUDINARY
    # -------------------------------------------------------------------------
    #
    # These values must ONLY exist on the backend.
    #
    # NEVER put CLOUDINARY_API_SECRET in the React/Vite frontend.
    #
    # Railway example:
    #
    # STORAGE_BACKEND=cloudinary
    # CLOUDINARY_CLOUD_NAME=...
    # CLOUDINARY_API_KEY=...
    # CLOUDINARY_API_SECRET=...

    CLOUDINARY_CLOUD_NAME: str = ""

    CLOUDINARY_API_KEY: str = ""

    CLOUDINARY_API_SECRET: str = ""

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

    META_APP_ID: str = ""

    META_APP_SECRET: str = ""

    META_CONFIG_ID: str = ""

    META_GRAPH_API_VERSION: str = "v25.0"

    META_OAUTH_REDIRECT_URI: str = (
        "http://localhost:5173/integrations/whatsapp/callback"
    )

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

    CORS_ORIGINS: List[str] = [
        "http://localhost:5173",
        "http://localhost:3000",
    ]


@lru_cache
def get_settings() -> Settings:
    """Return the cached application settings instance."""
    return Settings()


settings = get_settings()

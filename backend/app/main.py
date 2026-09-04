import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.config import settings
from app.core.rate_limit import RateLimitMiddleware
from app.services.ai import close_all_providers

logging.basicConfig(level=logging.INFO if not settings.DEBUG else logging.DEBUG)


@asynccontextmanager
async def lifespan(_: FastAPI):
    yield
    await close_all_providers()


app = FastAPI(
    title=settings.APP_NAME,
    description="PersonaAI — build an AI version of yourself that sells, supports, and represents you.",
    version="0.1.0",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RateLimitMiddleware)

app.include_router(api_router, prefix=settings.API_V1_PREFIX)


@app.get("/api/health", tags=["Health"])
async def health_check():
    return {"status": "ok", "service": settings.APP_NAME, "env": settings.APP_ENV}

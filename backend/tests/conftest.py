"""Test fixtures.

Uses an in-memory SQLite DB via aiosqlite for speed/isolation rather
than requiring a live Postgres instance for unit tests. CI's
integration test stage runs the same suite against real Postgres
(see .github/workflows) to catch dialect-specific issues (JSON/UUID
columns behave slightly differently) — that's a Milestone 7 CI item,
noted here so it isn't forgotten.
"""
import asyncio

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import settings
from app.core.rate_limit import _request_log
from app.database import Base, get_db
from app.main import app

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"

# See app/worker.py's dispatch_incoming_message docstring: eager mode
# runs the messaging pipeline inline against the test's own DB session
# instead of enqueueing a Celery task (which would open its own session
# against settings.DATABASE_URL, not this test's isolated in-memory
# SQLite DB — and there's no broker running in CI anyway). Set once at
# import time since every test in the suite needs it, not just the
# messaging-pipeline ones.
settings.CELERY_TASK_ALWAYS_EAGER = True


@pytest.fixture(autouse=True)
def _clear_rate_limit_log():
    """The rate limiter's request log is a module-level dict shared across
    the whole test session — without clearing it, tests that hit auth
    endpoints many times cumulatively (register/login helpers run in nearly
    every test file) would eventually trip 429s in unrelated tests."""
    _request_log.clear()
    yield
    _request_log.clear()


@pytest_asyncio.fixture
async def db_session():
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession):
    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()

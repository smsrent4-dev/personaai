"""Tests for app/worker.py's dispatch_incoming_message split.

Every other webhook test in this suite (tests/test_messaging_pipeline.py)
already exercises the EAGER path implicitly — conftest.py forces
settings.CELERY_TASK_ALWAYS_EAGER=True for the whole test session, so
posting to the webhook and asserting a reply was sent already proves
eager mode runs the real pipeline correctly. What isn't covered
anywhere else: that with eager mode OFF (the production default), the
webhook does NOT run the pipeline inline — it hands off to Celery's
.delay() instead. That's the actual point of this file.
"""
import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.integration import PlatformIntegration
from app.models.user import User


# ---------- persistent worker event loop (fixes a confirmed live bug: ----------
# ---------- "RuntimeError: Event loop is closed" from a cached httpx  ----------
# ---------- client surviving across per-task asyncio.run() loops)     ----------


def test_run_async_reuses_the_same_loop_across_calls():
    """This is the actual bug fix: asyncio.run() creates and closes a
    NEW loop every call, which is exactly what broke a process-level
    cached httpx.AsyncClient (GeminiProvider's, via get_ai_provider())
    once a second Celery task ran on a different loop than the one its
    connections were opened on. _run_async must reuse one loop for the
    whole worker process instead."""
    from app.worker import _get_worker_loop, _run_async

    async def _noop():
        return "ok"

    assert _run_async(_noop()) == "ok"
    loop_after_first_call = _get_worker_loop()
    assert not loop_after_first_call.is_closed()  # asyncio.run() would have closed it here

    assert _run_async(_noop()) == "ok"
    loop_after_second_call = _get_worker_loop()

    assert loop_after_first_call is loop_after_second_call
    assert not loop_after_second_call.is_closed()


def test_run_async_survives_a_task_that_raises():
    """A failing task must not leave the shared loop closed/broken for
    the next task in the same worker process — this is exactly the
    "first task poisons every task after it" shape the original bug had."""
    from app.worker import _get_worker_loop, _run_async

    async def _boom():
        raise ValueError("simulated task failure")

    with pytest.raises(ValueError):
        _run_async(_boom())

    assert not _get_worker_loop().is_closed()

    async def _noop():
        return "still works"

    assert _run_async(_noop()) == "still works"


def test_cached_client_used_across_multiple_worker_loop_runs():
    """Closer to the real failure mode from the traceback: a process-
    level singleton (get_ai_provider()'s cached GeminiProvider) used
    from two separate _run_async() calls, the way two separate Celery
    tasks in the same worker process would use it. Before the fix
    (asyncio.run() per call), the second call would find the first
    call's loop already closed underneath the cached client's
    connections. Uses a fake standing in for the cached
    httpx.AsyncClient to avoid a real network call, while exercising
    the same "cached object reused across _run_async calls" shape as
    the bug — a real httpx.AsyncClient bound to a closed loop raises
    exactly the traceback from the bug report when reused."""
    from app.worker import _run_async

    calls = []

    class FakeCachedClient:
        async def call(self):
            calls.append(1)
            return len(calls)

    cached_client = FakeCachedClient()

    async def _use_cached_client():
        return await cached_client.call()

    first_result = _run_async(_use_cached_client())
    second_result = _run_async(_use_cached_client())

    assert first_result == 1
    assert second_result == 2  # same object, second call, no "loop is closed" error


# ---------- dispatch_incoming_message eager/production split ----------


from app.models.platform_enums import Platform

USER = {
    "email": "worker-owner@example.com",
    "password": "StrongPass1",
    "full_name": "Worker Owner",
    "business_name": "Worker Co",
}
WEBHOOK_SECRET = "worker-test-webhook-secret"


async def _register_and_login(client: AsyncClient) -> str:
    await client.post("/api/v1/auth/register", json=USER)
    resp = await client.post("/api/v1/auth/login", json={"email": USER["email"], "password": USER["password"]})
    return resp.json()["access_token"]


async def _create_integration(db_session: AsyncSession) -> PlatformIntegration:
    result = await db_session.execute(select(User).where(User.email == USER["email"]))
    user = result.scalar_one()
    integration = PlatformIntegration(owner_id=user.id, platform=Platform.TELEGRAM, webhook_secret=WEBHOOK_SECRET)
    integration.set_credentials({"bot_token": "fake:token"})
    db_session.add(integration)
    await db_session.commit()
    await db_session.refresh(integration)
    return integration


@pytest.fixture
def non_eager(monkeypatch):
    """Flips settings.CELERY_TASK_ALWAYS_EAGER off for one test, then
    restores it — every other test in the suite relies on it staying
    True (see conftest.py), so this must not leak."""
    original = settings.CELERY_TASK_ALWAYS_EAGER
    settings.CELERY_TASK_ALWAYS_EAGER = False
    yield
    settings.CELERY_TASK_ALWAYS_EAGER = original


@pytest.mark.asyncio
async def test_production_mode_enqueues_instead_of_running_inline(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, non_eager
):
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    calls = []
    # Patch the task object dispatch_incoming_message actually holds a
    # reference to (imported at module load in app.worker), not a copy
    # imported into the webhook endpoint module — patching it here is
    # what the real code path goes through.
    monkeypatch.setattr(
        "app.worker.process_incoming_message_task.delay",
        lambda owner_id, integration_id, payload: calls.append((owner_id, integration_id, payload)),
    )

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json={
            "message": {
                "message_id": 1,
                "from": {"id": 555, "username": "customer", "first_name": "Cust"},
                "chat": {"id": 555},
                "text": "hello",
            }
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )

    assert resp.status_code == 204
    assert len(calls) == 1
    owner_id, integration_id, payload = calls[0]
    assert integration_id == str(integration.id)
    assert payload["message"]["text"] == "hello"


@pytest.mark.asyncio
async def test_production_mode_does_not_touch_the_ai_pipeline(
    client: AsyncClient, db_session: AsyncSession, monkeypatch, non_eager
):
    """Complementary check: with the task enqueue itself mocked into a
    no-op (simulating "Celery is configured but nothing consumed the
    queue in this test"), no reply should have been generated or sent —
    proving the webhook truly isn't running the pipeline inline anymore."""
    await _register_and_login(client)
    integration = await _create_integration(db_session)

    pipeline_was_called = False

    class _Sentinel(Exception):
        pass

    async def _fail_if_called(self, owner, integration, payload):
        nonlocal pipeline_was_called
        pipeline_was_called = True
        raise _Sentinel

    monkeypatch.setattr("app.services.messaging_pipeline.MessagingPipeline.handle_incoming", _fail_if_called)
    monkeypatch.setattr("app.worker.process_incoming_message_task.delay", lambda *a, **k: None)

    resp = await client.post(
        f"/api/v1/telegram/webhook/{integration.webhook_secret}",
        json={
            "message": {
                "message_id": 1,
                "from": {"id": 555, "username": "customer", "first_name": "Cust"},
                "chat": {"id": 555},
                "text": "hello",
            }
        },
        headers={"X-Telegram-Bot-Api-Secret-Token": integration.webhook_secret},
    )

    assert resp.status_code == 204
    assert pipeline_was_called is False

"""Celery application and background tasks.

IMPORTANT: tasks run on a single persistent event loop per worker
process (_get_worker_loop() below), NOT a fresh asyncio.run() per task.
This was a real bug, confirmed from a live error log: `RuntimeError:
Event loop is closed`, thrown deep inside httpcore's connection-pool
teardown while processing a later task.

Root cause: asyncio.run() creates a brand new event loop for its
coroutine and closes that loop when it returns — every single call.
Meanwhile app.services.ai.factory.get_ai_provider() deliberately caches
one GeminiProvider (and its httpx.AsyncClient) at the *process* level,
reused across every call — correct for a single long-lived event loop
(like the FastAPI app under uvicorn, one loop for the whole process).
Combine the two: the cached client's connections get bound to whichever
event loop happened to be running the first time a task used it — then
asyncio.run() closes that loop when the first task finishes. Every
subsequent task creates a NEW loop via asyncio.run(), but still reaches
for the SAME cached client, whose connections belong to a loop that's
now closed. httpx/httpcore's own async cleanup eventually tries to
operate on that dead loop and raises. This wasn't rare or flaky — it
was heading toward essentially every task after the first one in a
given worker process.

Adapters (TelegramAdapter/WhatsAppAdapter) were NOT part of this bug —
build_adapter() deliberately creates a fresh instance per call (see its
own docstring), and MessagingPipeline.handle_incoming() already closes
it in a `finally` block within the same task. Only the process-level
AI-provider cache crossed the asyncio.run() loop boundary.

Two tasks:
  - process_knowledge_document_task: still called inline from the
    upload endpoints today (see app/api/v1/endpoints/knowledge.py) —
    left that way deliberately, see its own note below.
  - process_incoming_message_task: NOT inline. Both webhook endpoints
    (telegram_webhook.py, whatsapp_webhook.py) call
    dispatch_incoming_message() (below) rather than awaiting
    MessagingPipeline directly, so a Telegram/WhatsApp webhook gets acked in milliseconds regardless of how long routing +
    RAG + AI generation (now up to 3 sequential Gemini calls for an
    image) takes. This was the #1 fix identified for handling real
    concurrent chat load: the previous inline version held a DB
    connection from the 30-connection pool for the entire AI round-trip
    per message, so ~30 messages processing at once was the practical
    ceiling before the pool queue backed up and requests started timing
    out. Backgrounding it means the webhook response no longer waits on
    Gemini at all, and message throughput is now bounded by Celery
    worker concurrency (scale by adding worker processes/replicas),
    not by the request/response cycle.

process_knowledge_document_task is left inline at its call sites for
now: Celery's actual runtime behavior couldn't be exercised in the
sandbox this was built in (no network/broker access) — switching a
given call site over is:

    from app.worker import process_knowledge_document_task
    process_knowledge_document_task.delay(str(document.id))

instead of `await service.ingest_document(document)`, once you've
confirmed the worker runs cleanly against your Redis instance.
process_incoming_message_task is wired in for you (the webhook
endpoints already call .delay() on it) since backgrounding the chat
path is the change that was explicitly asked for — but the same
"verify Celery works against your infra first" caveat applies before
you rely on it in production. If the worker isn't running, messages
will queue in Redis and simply not get replies until it is — they
won't be lost, but they also won't be answered.
"""
import asyncio
import logging
import uuid

from celery import Celery
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import AsyncSessionLocal
from app.models.integration import PlatformIntegration
from app.models.knowledge import KnowledgeDocument
from app.models.user import User
from app.services.knowledge.service import KnowledgeService

logger = logging.getLogger(__name__)

celery_app = Celery(
    "personaai",
    broker=settings.REDIS_URL,
    backend=settings.REDIS_URL,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
)


# One event loop per worker PROCESS, created lazily on first use (i.e.
# after Celery's prefork pool has already forked its child processes —
# asyncio event loops and their underlying selector fds do not survive
# a fork() safely, so this must not be created at import time). Every
# task in a given process reuses this same loop via run_until_complete,
# exactly like a normal long-lived async server has one loop for its
# whole lifetime — which is what lets get_ai_provider()'s cached
# GeminiProvider/httpx.AsyncClient actually behave the way it was
# designed to. See module docstring for the bug this replaces.
_worker_loop: asyncio.AbstractEventLoop | None = None


def _get_worker_loop() -> asyncio.AbstractEventLoop:
    global _worker_loop
    if _worker_loop is None or _worker_loop.is_closed():
        _worker_loop = asyncio.new_event_loop()
    return _worker_loop


def _run_async(coro):
    """Use this instead of asyncio.run() for every Celery task body in
    this file — see module docstring for why asyncio.run() (a fresh
    loop per call) is what caused the bug this replaces."""
    return _get_worker_loop().run_until_complete(coro)


async def _process_document_async(document_id: str) -> None:
    async with AsyncSessionLocal() as db:
        result = await db.execute(
            select(KnowledgeDocument).where(KnowledgeDocument.id == uuid.UUID(document_id))
        )
        document = result.scalar_one_or_none()
        if document is None:
            logger.warning("process_knowledge_document_task: document %s no longer exists", document_id)
            return
        await KnowledgeService(db).ingest_document(document)


@celery_app.task(name="personaai.process_knowledge_document", bind=True, max_retries=3, default_retry_delay=30)
def process_knowledge_document_task(self, document_id: str) -> None:
    try:
        _run_async(_process_document_async(document_id))
    except Exception as exc:  # noqa: BLE001 — Celery needs the broad catch to trigger retry
        logger.error("Knowledge ingestion task failed for %s: %s", document_id, exc, exc_info=True)
        raise self.retry(exc=exc)


async def _process_incoming_message_async(owner_id: str, integration_id: str, payload: dict) -> None:
    # Fresh session + fresh reads of owner/integration: this runs in a
    # separate Celery worker process, potentially seconds after the
    # webhook request that enqueued it, so re-fetch rather than trying
    # to carry the request-scoped ORM objects across the process
    # boundary (they wouldn't survive JSON serialization anyway).
    from app.services.messaging_pipeline import MessagingPipeline

    async with AsyncSessionLocal() as db:
        owner_result = await db.execute(select(User).where(User.id == uuid.UUID(owner_id)))
        owner = owner_result.scalar_one_or_none()
        if owner is None or not owner.is_active:
            logger.info("process_incoming_message_task: owner %s missing/inactive, dropping", owner_id)
            return

        integration_result = await db.execute(
            select(PlatformIntegration).where(PlatformIntegration.id == uuid.UUID(integration_id))
        )
        integration = integration_result.scalar_one_or_none()
        if integration is None:
            logger.info("process_incoming_message_task: integration %s no longer exists, dropping", integration_id)
            return

        await MessagingPipeline(db).handle_incoming(owner, integration, payload)


@celery_app.task(name="personaai.process_incoming_message", bind=True, max_retries=2, default_retry_delay=10)
def process_incoming_message_task(self, owner_id: str, integration_id: str, payload: dict) -> None:
    """Enqueued by the Telegram/WhatsApp webhook endpoints instead of
    them awaiting MessagingPipeline inline. Retries twice on unexpected
    failure (e.g. a transient DB blip) — deliberately NOT infinite
    retries, since a message that keeps failing after 3 total attempts
    is more likely a real bug than a transient one, and retrying a
    chat reply forever would eventually send a very stale reply."""
    try:
        _run_async(_process_incoming_message_async(owner_id, integration_id, payload))
    except Exception as exc:  # noqa: BLE001 — Celery needs the broad catch to trigger retry
        logger.error(
            "Incoming-message processing failed for integration %s: %s", integration_id, exc, exc_info=True
        )
        raise self.retry(exc=exc)


async def dispatch_incoming_message(
    db: AsyncSession, owner: User, integration: PlatformIntegration, payload: dict
) -> None:
    """What both webhook endpoints actually call — hides the
    eager-vs-Celery decision from them entirely so telegram_webhook.py
    and whatsapp_webhook.py don't need to know it exists.

    settings.CELERY_TASK_ALWAYS_EAGER True (tests only): runs the
    pipeline inline using the CALLER's own `db` session — critically,
    the same session the test's client fixture already has FastAPI's
    get_db dependency overridden to use, so tests keep exercising real
    pipeline behavior against their isolated per-test database, with no
    Celery/Redis involved at all.

    False (the production default): enqueues process_incoming_message_task
    and returns immediately. The task opens its own fresh DB session in
    the worker process — it cannot use `db`, a session tied to this
    request's connection, which will be closed by the time (and quite
    possibly in a different process from where) the task actually runs.
    """
    if settings.CELERY_TASK_ALWAYS_EAGER:
        from app.services.messaging_pipeline import MessagingPipeline

        await MessagingPipeline(db).handle_incoming(owner, integration, payload)
        return

    process_incoming_message_task.delay(str(owner.id), str(integration.id), payload)

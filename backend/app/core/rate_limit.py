"""Rate limiting for auth endpoints (login, register, forgot-password).

Backed by Redis (already part of this stack — settings.REDIS_URL,
shared with Celery) so the limit is enforced across every app
instance/worker, not per-process. That's the point of this rewrite:
the previous version was a plain in-process dict, which meant running
multiple app instances (the actual point of doing this — see
app/worker.py's docstring on backgrounding message processing, the
other half of the same scaling change) silently weakened it back down
to "10 requests per instance," not 10 total, since each instance
tracked its own counters with no shared state.

Falls back to the same in-memory sliding window if Redis is
unreachable — NOT because that's an equivalent substitute (it's back
to per-process limits, exactly the gap described above) but because a
rate limiter existing to protect a login page shouldn't itself be able
to take the login page down if Redis has a bad moment. A short cooldown
(_REDIS_RETRY_COOLDOWN_SECONDS) avoids retrying a dead Redis connection
on every single request during a real outage — one failed attempt,
then fall back to in-memory for the rest of the cooldown window before
trying Redis again.

Uses a Redis sorted set per (client_ip, path) as a real sliding window
(ZADD with a timestamp score, ZREMRANGEBYSCORE to expire entries older
than the window, ZCARD to count) — not a coarser fixed-window bucket,
so it matches the exact "N requests in the last 60 seconds" semantics
the in-memory version had, just shared across processes. The
ZADD+ZCARD pair runs as a pipeline, not a single atomic Lua script —
under very heavy concurrent hits from the same key it's possible a
handful of requests slip past the exact limit before the count is
visible to the next one. That's an acceptable tradeoff for
brute-force-slowing (the goal), not a hard security boundary that
needs perfect atomicity; noted rather than presented as airtight.
"""
import logging
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)

RATE_LIMITED_PREFIXES = ("/api/v1/auth/login", "/api/v1/auth/register", "/api/v1/auth/forgot-password")
WINDOW_SECONDS = 60
MAX_REQUESTS_PER_WINDOW = 10
_REDIS_RETRY_COOLDOWN_SECONDS = 30
_REDIS_SOCKET_TIMEOUT = 0.2  # fail fast — this must never be why a login request hangs

# In-memory fallback store. Also directly imported by tests/conftest.py's
# autouse fixture to reset state between tests — keep this name/shape
# stable even if the Redis path above it changes.
_request_log: dict[str, deque] = defaultdict(deque)

_redis_client = None
_redis_unavailable_until: float = 0.0


def _get_redis_client():
    global _redis_client
    if _redis_client is None:
        import redis.asyncio as redis_asyncio

        _redis_client = redis_asyncio.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=_REDIS_SOCKET_TIMEOUT,
            socket_timeout=_REDIS_SOCKET_TIMEOUT,
        )
    return _redis_client


async def _check_redis(key: str) -> bool | None:
    """Returns True (allowed) / False (rate-limited), or None if Redis
    itself couldn't be reached — callers fall back to _check_in_memory
    in that case."""
    global _redis_unavailable_until

    if time.monotonic() < _redis_unavailable_until:
        return None

    try:
        client = _get_redis_client()
        now = time.time()
        window_start = now - WINDOW_SECONDS
        member = f"{now}:{id(client)}:{time.perf_counter_ns()}"  # unique per call, avoids score collisions

        pipe = client.pipeline(transaction=True)
        pipe.zremrangebyscore(key, 0, window_start)
        pipe.zadd(key, {member: now})
        pipe.zcard(key)
        pipe.expire(key, WINDOW_SECONDS)
        _removed, _added, count, _expired = await pipe.execute()

        return count <= MAX_REQUESTS_PER_WINDOW
    except Exception:
        logger.warning(
            "Rate limiter: Redis unreachable, falling back to in-memory for %ds", _REDIS_RETRY_COOLDOWN_SECONDS
        )
        _redis_unavailable_until = time.monotonic() + _REDIS_RETRY_COOLDOWN_SECONDS
        return None


def _check_in_memory(key: str) -> bool:
    now = time.monotonic()
    log = _request_log[key]

    while log and now - log[0] > WINDOW_SECONDS:
        log.popleft()

    if len(log) >= MAX_REQUESTS_PER_WINDOW:
        return False

    log.append(now)
    return True


class RateLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(prefix) for prefix in RATE_LIMITED_PREFIXES):
            client_ip = request.client.host if request.client else "unknown"
            key = f"ratelimit:{client_ip}:{path}"

            allowed = await _check_redis(key)
            if allowed is None:
                allowed = _check_in_memory(key)

            if not allowed:
                return JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please wait a minute and try again."},
                )

        return await call_next(request)

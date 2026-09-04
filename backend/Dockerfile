FROM python:3.13-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

RUN useradd --create-home appuser && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# Number of worker PROCESSES (not threads) — each gets its own DB
# connection pool (see app/database.py's pool_size/max_overflow), so
# raising this without also raising Postgres's max_connections and/or
# lowering per-worker pool_size can exhaust the database's connection
# limit rather than helping. 4 is a reasonable single-container
# default; size it against your actual CPU count and Postgres's
# max_connections, not just raised blindly.
ENV WEB_CONCURRENCY=4

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:8000/api/health || exit 1

# gunicorn managing uvicorn workers, not uvicorn's own --workers flag:
# gunicorn supervises and restarts a crashed worker process, uvicorn's
# built-in multi-worker mode does not. This is the standard production
# pattern for FastAPI/uvicorn (see uvicorn's own deployment docs) — one
# process per CPU-bound unit of concurrency, all sharing this
# container's Redis/Postgres connections per the pool config above.
#
# This is what actually gets used when this image is deployed directly
# (Railway/Render/Fly/ECS/K8s/etc.) — docker-compose.yml overrides this
# CMD for local dev with a single `uvicorn --reload` process instead
# (hot-reload and multi-worker don't mix well, and local dev doesn't
# need the concurrency). For running multiple full CONTAINER replicas
# on top of this (not just multiple processes in one container), see
# docker-compose.prod.yml.
CMD ["sh", "-c", "gunicorn app.main:app -k uvicorn.workers.UvicornWorker -w ${WEB_CONCURRENCY} -b 0.0.0.0:8000 --access-logfile - --error-logfile -"]

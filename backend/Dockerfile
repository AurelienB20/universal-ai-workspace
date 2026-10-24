# syntax=docker/dockerfile:1
# Production image of the API. Build from the backend directory:
#   docker build -t uaw-backend .
# Run the database migrations before starting a new version:
#   docker run --rm --env-file .env uaw-backend alembic upgrade head

FROM ghcr.io/astral-sh/uv:0.13.0 AS uv

# --- Build stage: install the locked dependencies, then the project, in a venv ---
FROM python:3.12-slim-bookworm AS build
COPY --from=uv /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/app/.venv
WORKDIR /app
# Dependencies first: this layer is reused as long as the lock file does not change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-editable

# --- Runtime stage: the venv and the migrations only, no build tools ---
FROM python:3.12-slim-bookworm
RUN useradd --system --uid 10001 --no-create-home uaw
WORKDIR /app
COPY --from=build /app/.venv /app/.venv
COPY alembic.ini ./
COPY migrations ./migrations
# FORWARDED_ALLOW_IPS: addresses of the reverse proxies allowed to set
# X-Forwarded-For (rate limits use the client address). Set it to the proxy's
# address in production.
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    APP_ENV=production \
    LOG_FORMAT=json \
    FORWARDED_ALLOW_IPS=127.0.0.1
USER uaw
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=2)"]
# Access logs come from the application (with request IDs), not from uvicorn.
# One worker: rate limits are counted in memory, per process.
CMD ["uvicorn", "uaw.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "1", "--proxy-headers", "--no-access-log"]

"""FastAPI application factory.

Run locally with:
    uv run uvicorn uaw.main:create_app --factory --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI

from uaw import __version__
from uaw.api import ask, health, imports, repositories, search
from uaw.api.middleware import MaxBodySizeMiddleware, RequestContextMiddleware
from uaw.api.ratelimit import ConcurrencyLimiter, build_rate_limiters
from uaw.api.security import authenticate
from uaw.config import Settings, get_settings
from uaw.logging_config import configure_logging
from uaw.services import build_services

logger = logging.getLogger(__name__)

# Shared by every route that can spend provider tokens.
PROTECTED_RESPONSES: dict[int | str, dict[str, Any]] = {
    401: {"description": "Missing or invalid API key."},
    429: {"description": "Rate limit or daily usage budget reached (see Retry-After)."},
}


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        app.state.services = await build_services(app.state.settings, stack)
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level, settings.log_format)

    app = FastAPI(title="Universal AI Workspace", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.rate_limiters = build_rate_limiters(settings)
    app.state.ask_limiter = ConcurrencyLimiter(settings.max_concurrent_asks)
    # The last middleware added runs first: request IDs cover the 413 responses too.
    app.add_middleware(MaxBodySizeMiddleware, max_bytes=settings.max_request_body_kb * 1024)
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    # Admin, or visitors of the public demo when PUBLIC_IMPORTS_ENABLED (see imports.py).
    app.include_router(
        imports.router, dependencies=[Depends(authenticate)], responses=PROTECTED_RESPONSES
    )
    # Demo or admin; a demo key only reaches the DEMO_REPOSITORIES.
    for router in (repositories.router, search.router, ask.router):
        app.include_router(
            router, dependencies=[Depends(authenticate)], responses=PROTECTED_RESPONSES
        )

    if settings.api_key is None:
        logger.warning("API_KEY is not set: the API is open to anyone who can reach it")
    elif settings.demo_api_key is not None and not settings.demo_repositories:
        logger.warning("DEMO_API_KEY is set but DEMO_REPOSITORIES is empty: it reaches nothing")
    logger.info("Application created (env=%s)", settings.app_env)
    return app

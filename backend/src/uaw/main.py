"""FastAPI application factory.

Run locally with:
    uv run uvicorn uaw.main:create_app --factory --reload
"""

import logging
from collections.abc import AsyncIterator
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI

from uaw import __version__
from uaw.api import health, imports
from uaw.config import Settings, get_settings
from uaw.logging_config import configure_logging
from uaw.services import build_services

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    async with AsyncExitStack() as stack:
        app.state.services = await build_services(app.state.settings, stack)
        yield


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Universal AI Workspace", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.include_router(health.router)
    app.include_router(imports.router)

    logger.info("Application created (env=%s)", settings.app_env)
    return app

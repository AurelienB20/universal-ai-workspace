"""FastAPI application factory.

Run locally with:
    uv run uvicorn uaw.main:create_app --factory --reload
"""

import logging

from fastapi import FastAPI

from uaw import __version__
from uaw.api import health
from uaw.config import Settings, get_settings
from uaw.logging_config import configure_logging

logger = logging.getLogger(__name__)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings.log_level)

    app = FastAPI(title="Universal AI Workspace", version=__version__)
    app.state.settings = settings
    app.include_router(health.router)

    logger.info("Application created (env=%s)", settings.app_env)
    return app

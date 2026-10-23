import asyncio
import logging
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import text

from uaw import __version__
from uaw.api.deps import get_services
from uaw.services import Services

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])

ServicesDep = Annotated[Services, Depends(get_services)]

READINESS_TIMEOUT_SECONDS = 2.0


class HealthResponse(BaseModel):
    status: Literal["ok"]
    version: str


class ReadinessResponse(BaseModel):
    status: Literal["ok"]
    database: Literal["ok"]


@router.get("/health")
def health() -> HealthResponse:
    """Liveness probe: the process is up and serving requests."""
    return HealthResponse(status="ok", version=__version__)


@router.get(
    "/health/ready",
    responses={503: {"description": "The database is unreachable."}},
)
async def ready(services: ServicesDep) -> ReadinessResponse:
    """Readiness probe: the server can handle requests (its database answers)."""
    try:
        async with asyncio.timeout(READINESS_TIMEOUT_SECONDS):
            async with services.session_factory() as session:
                await session.execute(text("SELECT 1"))
    except Exception as exc:
        logger.warning("Readiness check failed: %s", type(exc).__name__)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE, detail="The database is unreachable."
        ) from exc
    return ReadinessResponse(status="ok", database="ok")

"""Repository imports.

The admin imports any public repository. With PUBLIC_IMPORTS_ENABLED, a visitor of the
public demo (demo key and visitor id) can import one too, under stricter limits and
daily quotas; the visitor then reads it, and nobody else does, for VISITOR_ACCESS_HOURS.
"""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.api.deps import get_services
from uaw.api.ratelimit import enforce_rate_limit, rate_limited
from uaw.api.security import Caller, CallerDep
from uaw.api.usage import ensure_within_budget
from uaw.config import Settings
from uaw.connectors.github.url import (
    GitHubRepoRef,
    InvalidRepositoryUrlError,
    parse_github_repo_url,
)
from uaw.domain.jobs import IngestionJob
from uaw.services import Services
from uaw.storage.jobs import JobStore
from uaw.storage.visitors import VisitorAccessStore

router = APIRouter(prefix="/imports", tags=["imports"])

ServicesDep = Annotated[Services, Depends(get_services)]

# A full queue frees up as soon as the running import ends: a few minutes at most.
QUEUE_FULL_RETRY_AFTER_SECONDS = 60


class ImportRequest(BaseModel):
    # The parser enforces the real rules; this only bounds the request size.
    url: str = Field(max_length=1000, examples=["https://github.com/pallets/flask"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    dependencies=[Depends(rate_limited("imports"))],
    responses={
        200: {
            "description": "An import of this repository is already in progress, or (for a "
            "visitor) the repository is already indexed: no new import is needed."
        },
        403: {"description": "This key cannot import (public imports are disabled)."},
        422: {"description": "The URL is not a supported GitHub repository URL."},
        429: {"description": "A daily import quota is reached (see Retry-After)."},
        503: {"description": "Imports are disabled on this server, or the queue is full."},
    },
)
async def create_import(
    body: ImportRequest,
    services: ServicesDep,
    request: Request,
    response: Response,
    caller: CallerDep,
) -> IngestionJob:
    """Start importing a public GitHub repository. Poll the returned job for progress."""
    settings: Settings = request.app.state.settings
    visitor_id = _importing_visitor(settings, caller)
    try:
        ref = parse_github_repo_url(body.url)
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if services.runner is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Repository imports are disabled: no embedding API key is configured.",
        )
    await ensure_within_budget(services, "voyage")

    async with services.session_factory.begin() as session:
        if visitor_id is None:
            job, created = await JobStore(session).create_or_get_active(ref.full_name)
        else:
            job, created = await _queue_for_visitor(request, session, ref, visitor_id)
    # Submitted after the commit, so the background task always finds the job.
    if created:
        services.runner.submit(job.id, ref, visitor=visitor_id is not None)
    else:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/imports/{job.id}"
    return job


@router.get(
    "/{job_id}",
    responses={
        403: {"description": "This key cannot import (public imports are disabled)."},
        404: {"description": "Unknown import job."},
    },
)
async def get_import(
    job_id: uuid.UUID, services: ServicesDep, request: Request, caller: CallerDep
) -> IngestionJob:
    """An import's progress. A visitor sees only the imports of repositories they
    asked for."""
    visitor_id = _importing_visitor(request.app.state.settings, caller)
    async with services.session_factory() as session:
        job = await JobStore(session).get(job_id)
        # A visitor sees an import only while they may read its repository.
        if (
            job is not None
            and visitor_id is not None
            and not await VisitorAccessStore(session).can_read(visitor_id, job.repository)
        ):
            job = None
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Import job not found.")
    return job


def _importing_visitor(settings: Settings, caller: Caller) -> uuid.UUID | None:
    """The visitor importing (None: the admin), or the reason this caller cannot."""
    if caller.role == "admin":
        return None
    if not settings.public_imports_enabled:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This API key cannot do that.")
    if caller.visitor_id is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="An X-Visitor-Id header is required."
        )
    return caller.visitor_id


async def _queue_for_visitor(
    request: Request, session: AsyncSession, ref: GitHubRepoRef, visitor_id: uuid.UUID
) -> tuple[IngestionJob, bool]:
    """Give the visitor access to ``ref`` and queue its import, within the quotas.

    A repository that is already indexed is not imported again: the visitor reads the
    existing snapshot at once, for free. It also keeps a complete snapshot imported by
    the admin from being replaced by one cut down to the visitor limits.
    """
    settings: Settings = request.app.state.settings
    jobs = JobStore(session)
    access = timedelta(hours=settings.visitor_access_hours)
    done = await jobs.latest_succeeded(ref.full_name)
    if done is not None:
        await VisitorAccessStore(session).grant(visitor_id, ref.full_name, access)
        return done, False

    enforce_rate_limit(request, "visitor_imports")
    await jobs.lock_visitor_imports()
    now = datetime.now(UTC)
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    until_tomorrow = {"Retry-After": str(int((midnight + timedelta(days=1) - now).total_seconds()))}
    limit = settings.visitor_imports_per_visitor_per_day
    if await jobs.count_visitor_imports(midnight, visitor_id) >= limit:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"You can import {limit} repositories a day. Try again tomorrow.",
            headers=until_tomorrow,
        )
    if await jobs.count_visitor_imports(midnight) >= settings.visitor_imports_per_day:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="The demo has reached its import limit for today. Try again tomorrow.",
            headers=until_tomorrow,
        )
    # The running import plus the ones waiting behind it.
    if await jobs.count_active_visitor_imports() > settings.visitor_import_queue:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Other imports are in progress. Try again in a few minutes.",
            headers={"Retry-After": str(QUEUE_FULL_RETRY_AFTER_SECONDS)},
        )
    job, created = await jobs.create_or_get_active(ref.full_name, visitor_id)
    await VisitorAccessStore(session).grant(visitor_id, ref.full_name, access)
    return job, created

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from uaw.api.deps import get_services
from uaw.connectors.github.url import InvalidRepositoryUrlError, parse_github_repo_url
from uaw.domain.jobs import IngestionJob
from uaw.services import Services
from uaw.storage.jobs import JobStore

router = APIRouter(prefix="/imports", tags=["imports"])

ServicesDep = Annotated[Services, Depends(get_services)]


class ImportRequest(BaseModel):
    # The parser enforces the real rules; this only bounds the request size.
    url: str = Field(max_length=1000, examples=["https://github.com/pallets/flask"])


@router.post(
    "",
    status_code=status.HTTP_202_ACCEPTED,
    responses={
        200: {"description": "An import of this repository is already in progress."},
        422: {"description": "The URL is not a supported GitHub repository URL."},
        503: {"description": "Imports are disabled on this server."},
    },
)
async def create_import(
    body: ImportRequest, services: ServicesDep, response: Response
) -> IngestionJob:
    """Start importing a public GitHub repository. Poll the returned job for progress."""
    try:
        ref = parse_github_repo_url(body.url)
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    if services.runner is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Repository imports are disabled: no embedding API key is configured.",
        )

    async with services.session_factory.begin() as session:
        job, created = await JobStore(session).create_or_get_active(ref.full_name)
    # Submitted after the commit, so the background task always finds the job.
    if created:
        services.runner.submit(job.id, ref)
    else:
        response.status_code = status.HTTP_200_OK
    response.headers["Location"] = f"/imports/{job.id}"
    return job


@router.get("/{job_id}", responses={404: {"description": "Unknown import job."}})
async def get_import(job_id: uuid.UUID, services: ServicesDep) -> IngestionJob:
    async with services.session_factory() as session:
        job = await JobStore(session).get(job_id)
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Import job not found.")
    return job

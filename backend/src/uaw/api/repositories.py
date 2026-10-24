from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from uaw.api.deps import get_services
from uaw.api.security import RoleDep, is_allowed, require_admin
from uaw.connectors.github.url import InvalidRepositoryUrlError, parse_github_full_name
from uaw.services import Services
from uaw.storage.jobs import JobStore
from uaw.storage.repositories import RepositoryCatalog, RepositorySummary
from uaw.storage.store import SnapshotStore

router = APIRouter(prefix="/repositories", tags=["repositories"])

ServicesDep = Annotated[Services, Depends(get_services)]


@router.get("")
async def list_repositories(
    services: ServicesDep, request: Request, role: RoleDep
) -> list[RepositorySummary]:
    """The repositories that can be searched and questioned, sorted by name.

    A demo key only sees the DEMO_REPOSITORIES.
    """
    async with services.session_factory() as session:
        summaries = await RepositoryCatalog(session).list_ready()
    settings = request.app.state.settings
    return [summary for summary in summaries if is_allowed(settings, role, summary.repository)]


@router.delete(
    "/{owner}/{name}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[Depends(require_admin)],
    responses={
        403: {"description": "Admin key required."},
        404: {"description": "Unknown repository."},
        409: {"description": "An import of this repository is in progress."},
        422: {"description": "Invalid repository name."},
    },
)
async def delete_repository(owner: str, name: str, services: ServicesDep) -> Response:
    """Delete a repository with all its snapshots, documents and passages.

    Token usage records are kept: that usage was billed anyway.
    """
    try:
        ref = parse_github_full_name(f"{owner}/{name}")
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    async with services.session_factory.begin() as session:
        if await JobStore(session).has_active(ref.full_name):
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail=f"An import of {ref.full_name} is in progress. Try again once it ends.",
            )
        if not await SnapshotStore(session).delete_repository(ref.full_name):
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=f"{ref.full_name} is not imported."
            )
    return Response(status_code=status.HTTP_204_NO_CONTENT)

from typing import Annotated

from fastapi import APIRouter, Depends, Request

from uaw.api.deps import get_services
from uaw.api.security import RoleDep, is_allowed
from uaw.services import Services
from uaw.storage.repositories import RepositoryCatalog, RepositorySummary

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

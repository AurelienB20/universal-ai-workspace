"""API keys, roles and visitors.

Two roles: "admin" (API_KEY: every route) and "demo" (DEMO_API_KEY: questions and
searches on the DEMO_REPOSITORIES only). A public web interface holds the demo key,
so a visitor can never import a repository or reach one outside the allowlist.

The web interface also sends each visitor's anonymous identifier (X-Visitor-Id). It
is trusted only with the demo key, which only that server holds: a visitor then also
reads the repositories they imported themselves, and nobody else's.
"""

import hmac
import uuid
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import SecretStr

from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.retrieval.retriever import RepositoryNotIndexedError
from uaw.services import Services
from uaw.storage.visitors import VisitorAccessStore

Role = Literal["demo", "admin"]

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Required when the server is configured with API_KEY.",
)


def _matches(given: bytes, expected: SecretStr | None) -> bool:
    if expected is None:
        return False
    # Constant-time comparison: the response time does not reveal how much matched.
    return hmac.compare_digest(given, expected.get_secret_value().encode())


def authenticate(
    request: Request, api_key: Annotated[str | None, Security(api_key_header)]
) -> Role:
    """The role of the caller. Raises 401 for a missing or unknown key."""
    settings: Settings = request.app.state.settings
    if settings.api_key is None:
        return "admin"  # local development: no key configured, the API is open
    given = (api_key or "").encode()
    # Both comparisons always run, so the timing does not reveal which key matched.
    # Configured keys are never empty (an empty value means "not set").
    is_admin = _matches(given, settings.api_key)
    is_demo = _matches(given, settings.demo_api_key)
    if is_admin:
        return "admin"
    if is_demo:
        return "demo"
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key.")


RoleDep = Annotated[Role, Depends(authenticate)]


def require_admin(role: RoleDep) -> None:
    if role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="This API key cannot do that.")


@dataclass(frozen=True)
class Caller:
    role: Role
    # The visitor of the public demo, as identified by the web interface. Always None
    # for the admin key, which reads every repository anyway.
    visitor_id: uuid.UUID | None = None


def identify(
    role: RoleDep,
    visitor: Annotated[
        str | None,
        Header(
            alias="X-Visitor-Id",
            description="Anonymous visitor identifier (UUID), sent by the web interface "
            "with the demo key.",
        ),
    ] = None,
) -> Caller:
    if role != "demo" or visitor is None:
        return Caller(role)
    try:
        visitor_id = uuid.UUID(visitor)
    except ValueError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, detail="Invalid X-Visitor-Id header."
        ) from exc
    return Caller(role, visitor_id)


CallerDep = Annotated[Caller, Depends(identify)]


def is_allowed(settings: Settings, role: Role, repository: str) -> bool:
    """Whether ``role`` may read ``repository`` ("owner/name", any case), visitors'
    own repositories aside."""
    return role == "admin" or repository.lower() in settings.demo_repositories


async def ensure_repository_allowed(
    request: Request, services: Services, caller: Caller, ref: GitHubRepoRef
) -> None:
    """Refuse a demo caller a repository outside the allowlist, unless the visitor
    imported it.

    The answer is the same 404 as for a repository that was never imported, so that
    a demo key does not reveal what else the server holds.
    """
    if is_allowed(request.app.state.settings, caller.role, ref.full_name):
        return
    if caller.visitor_id is not None:
        async with services.session_factory() as session:
            if await VisitorAccessStore(session).can_read(caller.visitor_id, ref.full_name):
                return
    raise HTTPException(
        status.HTTP_404_NOT_FOUND, detail=str(RepositoryNotIndexedError.for_repository(ref))
    )

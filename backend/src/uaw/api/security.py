"""API keys and roles.

Two roles: "admin" (API_KEY: every route) and "demo" (DEMO_API_KEY: questions and
searches on the DEMO_REPOSITORIES only). A public web interface holds the demo key,
so a visitor can never import a repository or reach one outside the allowlist.
"""

import hmac
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader
from pydantic import SecretStr

from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.retrieval.retriever import RepositoryNotIndexedError

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


def is_allowed(settings: Settings, role: Role, repository: str) -> bool:
    """Whether ``role`` may read ``repository`` ("owner/name", any case)."""
    return role == "admin" or repository.lower() in settings.demo_repositories


def ensure_repository_allowed(request: Request, role: Role, ref: GitHubRepoRef) -> None:
    """Refuse a demo caller a repository outside the allowlist.

    The answer is the same 404 as for a repository that was never imported, so that
    a demo key does not reveal what else the server holds.
    """
    if not is_allowed(request.app.state.settings, role, ref.full_name):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, detail=str(RepositoryNotIndexedError.for_repository(ref))
        )

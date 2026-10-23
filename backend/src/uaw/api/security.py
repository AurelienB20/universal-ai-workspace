"""API key check for the routes that use the paid model providers."""

import hmac
from typing import Annotated

from fastapi import HTTPException, Request, Security, status
from fastapi.security import APIKeyHeader

from uaw.config import Settings

api_key_header = APIKeyHeader(
    name="X-API-Key",
    auto_error=False,
    description="Required when the server is configured with API_KEY.",
)


def require_api_key(
    request: Request, api_key: Annotated[str | None, Security(api_key_header)]
) -> None:
    settings: Settings = request.app.state.settings
    if settings.api_key is None:
        return  # local development: no key configured
    expected = settings.api_key.get_secret_value().encode()
    # Constant-time comparison: the response time does not reveal how much matched.
    if api_key is None or not hmac.compare_digest(api_key.encode(), expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing or invalid API key.")

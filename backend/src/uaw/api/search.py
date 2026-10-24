from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from uaw.api.deps import get_services
from uaw.api.ratelimit import rate_limited
from uaw.api.security import RoleDep, ensure_repository_allowed
from uaw.api.usage import reserved, tracked
from uaw.config import Settings
from uaw.connectors.github.url import InvalidRepositoryUrlError, parse_github_full_name
from uaw.embeddings.errors import EmbeddingError
from uaw.retrieval.retriever import (
    EmbeddingModelMismatchError,
    RepositoryNotIndexedError,
    SearchResult,
)
from uaw.services import Services
from uaw.usage.meter import Provider

router = APIRouter(prefix="/search", tags=["search"])

ServicesDep = Annotated[Services, Depends(get_services)]

MAX_QUERY_CHARS = 2000
MAX_TOP_K = 50


class SearchRequest(BaseModel):
    repository: str = Field(max_length=200, examples=["pallets/itsdangerous"])
    query: str = Field(
        min_length=1, max_length=MAX_QUERY_CHARS, examples=["How are signatures verified?"]
    )
    top_k: int = Field(default=10, ge=1, le=MAX_TOP_K)


@router.post(
    "",
    dependencies=[Depends(rate_limited("search"))],
    responses={
        404: {"description": "The repository has not been imported, or is still indexing."},
        409: {"description": "The repository must be imported again (embedding model changed)."},
        422: {"description": "Invalid repository name or query."},
        503: {"description": "Search is disabled, or the embedding service is unavailable."},
    },
)
async def search(
    body: SearchRequest, services: ServicesDep, request: Request, role: RoleDep
) -> SearchResult:
    """Return the passages of an imported repository closest to the query, best first.

    This is retrieval only: no answer is generated.
    """
    try:
        ref = parse_github_full_name(body.repository)
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    ensure_repository_allowed(request, role, ref)
    query = body.query.strip()
    if not query:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The query is empty.")
    if services.retriever is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search is disabled: no embedding API key is configured.",
        )
    settings: Settings = request.app.state.settings
    estimates: dict[Provider, int] = {"voyage": settings.query_reserved_voyage_tokens}

    try:
        async with reserved(services, estimates), tracked(services, "search", ref.full_name):
            return await services.retriever.search(ref, query, top_k=body.top_k)
    except RepositoryNotIndexedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmbeddingModelMismatchError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except EmbeddingError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

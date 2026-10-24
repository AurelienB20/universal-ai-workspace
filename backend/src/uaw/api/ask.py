from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from uaw.api.deps import get_services
from uaw.api.ratelimit import ConcurrencyLimiter, rate_limited
from uaw.api.security import RoleDep, ensure_repository_allowed
from uaw.api.usage import reserved, tracked
from uaw.config import Settings
from uaw.connectors.github.url import (
    GitHubRepoRef,
    InvalidRepositoryUrlError,
    parse_github_full_name,
)
from uaw.embeddings.errors import EmbeddingError
from uaw.generation.answerer import Answer
from uaw.generation.errors import GenerationError, GenerationRefusedError
from uaw.retrieval.retriever import EmbeddingModelMismatchError, RepositoryNotIndexedError
from uaw.services import Services
from uaw.usage.meter import Provider

router = APIRouter(prefix="/ask", tags=["ask"])

ServicesDep = Annotated[Services, Depends(get_services)]

MAX_QUESTION_CHARS = 2000


class AskRequest(BaseModel):
    repository: str = Field(max_length=200, examples=["pallets/itsdangerous"])
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        examples=["How are expired tokens detected?"],
    )


@router.post(
    "",
    dependencies=[Depends(rate_limited("ask"))],
    responses={
        404: {"description": "The repository has not been imported, or is still indexing."},
        409: {"description": "The repository must be imported again (embedding model changed)."},
        422: {"description": "Invalid request, or the model declined to answer."},
        503: {
            "description": "Answers are disabled, the server is busy (see Retry-After), "
            "or a model provider is unavailable."
        },
    },
)
async def ask(body: AskRequest, services: ServicesDep, request: Request, role: RoleDep) -> Answer:
    """Answer a question about an imported repository, with citations to exact lines.

    Citations are checked by the server: each one points to a passage that was really
    retrieved, at the indexed commit.
    """
    try:
        ref = parse_github_full_name(body.repository)
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    ensure_repository_allowed(request, role, ref)
    question = body.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The question is empty.")
    return await generate_answer(services, request, ref, question)


async def generate_answer(
    services: Services, request: Request, ref: GitHubRepoRef, question: str
) -> Answer:
    """Answer ``question`` within the concurrency limit and the daily budgets, and
    record its usage. Errors are translated into HTTP responses.

    Shared by POST /ask and the generation of cached answers.
    """
    if services.answerer is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answers are disabled: an embedding and an Anthropic API key are required.",
        )
    settings: Settings = request.app.state.settings
    limiter: ConcurrencyLimiter = request.app.state.ask_limiter
    estimates: dict[Provider, int] = {
        "voyage": settings.query_reserved_voyage_tokens,
        "anthropic": settings.ask_reserved_llm_tokens,
    }

    try:
        # Usage is recorded (tracked) before the reservation is released, so the
        # tokens are always counted by one or the other.
        with limiter.slot():
            async with reserved(services, estimates), tracked(services, "ask", ref.full_name):
                return await services.answerer.ask(ref, question)
    except RepositoryNotIndexedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmbeddingModelMismatchError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GenerationRefusedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (EmbeddingError, GenerationError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

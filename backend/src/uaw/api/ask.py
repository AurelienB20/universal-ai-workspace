from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from uaw.api.deps import get_services
from uaw.api.ratelimit import rate_limited
from uaw.api.usage import ensure_within_budget, tracked
from uaw.connectors.github.url import InvalidRepositoryUrlError, parse_github_full_name
from uaw.embeddings.errors import EmbeddingError
from uaw.generation.answerer import Answer
from uaw.generation.errors import GenerationError, GenerationRefusedError
from uaw.retrieval.retriever import EmbeddingModelMismatchError, RepositoryNotIndexedError
from uaw.services import Services

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
        503: {"description": "Answers are disabled, or a model provider is unavailable."},
    },
)
async def ask(body: AskRequest, services: ServicesDep) -> Answer:
    """Answer a question about an imported repository, with citations to exact lines.

    Citations are checked by the server: each one points to a passage that was really
    retrieved, at the indexed commit.
    """
    try:
        ref = parse_github_full_name(body.repository)
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    question = body.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The question is empty.")
    if services.answerer is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answers are disabled: an embedding and an Anthropic API key are required.",
        )
    await ensure_within_budget(services, "voyage", "anthropic")

    try:
        async with tracked(services, "ask", ref.full_name):
            return await services.answerer.ask(ref, question)
    except RepositoryNotIndexedError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except EmbeddingModelMismatchError as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GenerationRefusedError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    except (EmbeddingError, GenerationError) as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc

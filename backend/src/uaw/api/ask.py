import asyncio
import logging
from collections.abc import AsyncGenerator, AsyncIterator
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from uaw.api.deps import get_services
from uaw.api.ratelimit import ConcurrencyLimiter, rate_limited
from uaw.api.security import Caller, CallerDep, ensure_repository_allowed
from uaw.api.usage import reserved, tracked
from uaw.config import Settings
from uaw.connectors.github.url import (
    GitHubRepoRef,
    InvalidRepositoryUrlError,
    parse_github_full_name,
)
from uaw.embeddings.errors import EmbeddingError
from uaw.generation.answerer import Answer, Answerer, AnswerEvent, SourcesFound
from uaw.generation.claude import AnswerDelta, AnswerRestart
from uaw.generation.errors import GenerationError, GenerationRefusedError
from uaw.retrieval.retriever import EmbeddingModelMismatchError, RepositoryNotIndexedError
from uaw.services import Services
from uaw.usage.meter import Provider

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ask", tags=["ask"])

ServicesDep = Annotated[Services, Depends(get_services)]

MAX_QUESTION_CHARS = 2000

ERROR_RESPONSES: dict[int | str, dict[str, str]] = {
    404: {"description": "The repository has not been imported, or is still indexing."},
    409: {"description": "The repository must be imported again (embedding model changed)."},
    422: {"description": "Invalid request, or the model declined to answer."},
    503: {
        "description": "Answers are disabled, the server is busy (see Retry-After), "
        "or a model provider is unavailable."
    },
}

# Proxies must pass each event on at once instead of buffering or compressing them.
STREAM_HEADERS = {"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no"}


class AskRequest(BaseModel):
    repository: str = Field(max_length=200, examples=["pallets/itsdangerous"])
    question: str = Field(
        min_length=1,
        max_length=MAX_QUESTION_CHARS,
        examples=["How are expired tokens detected?"],
    )


@router.post("", dependencies=[Depends(rate_limited("ask"))], responses=ERROR_RESPONSES)
async def ask(
    body: AskRequest, services: ServicesDep, request: Request, caller: CallerDep
) -> Answer:
    """Answer a question about an imported repository, with citations to exact lines.

    Citations are checked by the server: each one points to a passage that was really
    retrieved, at the indexed commit.
    """
    ref, question = await _checked(body, request, services, caller)
    return await generate_answer(services, request, ref, question)


@router.post(
    "/stream",
    dependencies=[Depends(rate_limited("ask"))],
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-sent events: `sources`, then `delta` (draft text) and "
            "`reset` (discard the draft), then `done` (the checked answer, as returned by "
            "POST /ask) or `error`.",
            "content": {"text/event-stream": {}},
        },
        **ERROR_RESPONSES,
    },
)
async def ask_stream(
    body: AskRequest, services: ServicesDep, request: Request, caller: CallerDep
) -> StreamingResponse:
    """POST /ask, streamed: the sources as soon as they are found, then the answer
    while it is written.

    The streamed text is a draft: the `done` event carries the answer with its
    citations checked, which replaces it. Errors found before the stream starts
    (unknown repository, busy server, budget) are ordinary HTTP errors.
    """
    ref, question = await _checked(body, request, services, caller)
    stream = _AnswerStream(services, request, ref, question)
    sources = await stream.first()
    return StreamingResponse(
        stream.events(sources), media_type="text/event-stream", headers=STREAM_HEADERS
    )


async def _checked(
    body: AskRequest, request: Request, services: Services, caller: Caller
) -> tuple[GitHubRepoRef, str]:
    try:
        ref = parse_github_full_name(body.repository)
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
    await ensure_repository_allowed(request, services, caller, ref)
    question = body.question.strip()
    if not question:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail="The question is empty.")
    return ref, question


async def generate_answer(
    services: Services, request: Request, ref: GitHubRepoRef, question: str
) -> Answer:
    """Answer ``question`` within the concurrency limit and the daily budgets, and
    record its usage. Errors are translated into HTTP responses.

    Shared by POST /ask and the generation of cached answers.
    """
    answerer = _answerer(services)
    try:
        async with _within_limits(services, request, ref):
            return await answerer.ask(ref, question)
    except Exception as exc:
        error = _http_error(exc)
        if error is None:
            raise
        raise error from exc


def _answerer(services: Services) -> Answerer:
    if services.answerer is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Answers are disabled: an embedding and an Anthropic API key are required.",
        )
    return services.answerer


@asynccontextmanager
async def _within_limits(
    services: Services, request: Request, ref: GitHubRepoRef
) -> AsyncIterator[None]:
    """The concurrency slot, the budget reservation and the usage record of one answer.

    Usage is recorded (tracked) before the reservation is released, so the tokens are
    always counted by one or the other.
    """
    settings: Settings = request.app.state.settings
    limiter: ConcurrencyLimiter = request.app.state.ask_limiter
    estimates: dict[Provider, int] = {
        "voyage": settings.query_reserved_voyage_tokens,
        "anthropic": settings.ask_reserved_llm_tokens,
    }
    with limiter.slot():
        async with reserved(services, estimates), tracked(services, "ask", ref.full_name):
            yield


def _http_error(exc: Exception) -> HTTPException | None:
    """Answering errors -> HTTP errors (None for any other error)."""
    if isinstance(exc, RepositoryNotIndexedError):
        return HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, EmbeddingModelMismatchError):
        return HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, GenerationRefusedError):
        return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    if isinstance(exc, EmbeddingError | GenerationError):
        return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, HTTPException):
        # Raised by the limits themselves: busy server, budget spent.
        return exc
    return None


# Streams whose answer is still being written. asyncio keeps only weak references to
# tasks: without this set, a running answer could be garbage collected.
_running: set[asyncio.Task[None]] = set()


class _AnswerStream:
    """One streamed answer, written by its own task into a queue.

    The task holds the concurrency slot, the budget reservation and the usage record
    from start to end, and keeps them out of the response's task: the usage meter is a
    context variable, which must be set and reset in the same task. When the client goes
    away, the response stops reading and cancels the task; the tokens already generated
    are still recorded.
    """

    def __init__(
        self, services: Services, request: Request, ref: GitHubRepoRef, question: str
    ) -> None:
        answerer = _answerer(services)
        # Created here, entered and left by the task.
        limits = _within_limits(services, request, ref)
        self._queue: asyncio.Queue[AnswerEvent | Exception | None] = asyncio.Queue()
        self._task = asyncio.create_task(self._run(answerer, limits, ref, question))
        _running.add(self._task)
        self._task.add_done_callback(_running.discard)

    async def _run(
        self,
        answerer: Answerer,
        limits: AbstractAsyncContextManager[None],
        ref: GitHubRepoRef,
        question: str,
    ) -> None:
        try:
            async with limits:
                async for event in answerer.ask_stream(ref, question):
                    self._queue.put_nowait(event)
        except Exception as exc:
            self._queue.put_nowait(exc)
        finally:
            self._queue.put_nowait(None)

    async def first(self) -> SourcesFound:
        """The sources, or the error that came before them, as an HTTP error."""
        try:
            item = await self._queue.get()
        except BaseException:
            self._task.cancel()
            raise
        if isinstance(item, Exception):
            error = _http_error(item)
            if error is None:
                raise item
            raise error from item
        if not isinstance(item, SourcesFound):
            raise RuntimeError(f"Unexpected first answer event: {item!r}")
        return item

    async def events(self, sources: SourcesFound) -> AsyncGenerator[str]:
        try:
            yield _event("sources", sources.model_dump_json())
            while (item := await self._queue.get()) is not None:
                if isinstance(item, Exception):
                    yield _event("error", _error_data(item))
                elif isinstance(item, AnswerDelta):
                    yield _event("delta", item.model_dump_json())
                elif isinstance(item, AnswerRestart):
                    yield _event("reset", "{}")
                elif isinstance(item, Answer):
                    yield _event("done", item.model_dump_json())
        finally:
            # A no-op once the answer is complete; otherwise the client went away.
            self._task.cancel()


def _event(name: str, data: str) -> str:
    # JSON never contains a raw line break, so each event's data fits on one line.
    return f"event: {name}\ndata: {data}\n\n"


def _error_data(exc: Exception) -> str:
    error = _http_error(exc)
    if error is not None:
        return ErrorEvent(status=error.status_code, detail=str(error.detail)).model_dump_json()
    logger.error("A streamed answer failed", exc_info=exc)
    return ErrorEvent(
        status=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="The answer could not be completed."
    ).model_dump_json()


class ErrorEvent(BaseModel):
    status: int
    detail: str

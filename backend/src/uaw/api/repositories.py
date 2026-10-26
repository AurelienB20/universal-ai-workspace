from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, ConfigDict, Field, StringConstraints

from uaw.api.ask import MAX_QUESTION_CHARS, generate_answer
from uaw.api.deps import get_services
from uaw.api.security import CallerDep, ensure_repository_allowed, is_allowed, require_admin
from uaw.connectors.github.url import (
    GitHubRepoRef,
    InvalidRepositoryUrlError,
    parse_github_full_name,
)
from uaw.generation.answerer import Answer
from uaw.retrieval.retriever import RepositoryNotIndexedError
from uaw.services import Services
from uaw.storage.cached_answers import CachedAnswer, CachedAnswerStore, Language
from uaw.storage.jobs import JobStore
from uaw.storage.repositories import RepositoryCatalog, RepositorySummary
from uaw.storage.search import ChunkSearch
from uaw.storage.store import SnapshotStore
from uaw.storage.visitors import VisitorAccessStore

router = APIRouter(prefix="/repositories", tags=["repositories"])

ServicesDep = Annotated[Services, Depends(get_services)]


class RepositoryListing(RepositorySummary):
    # End of the visitor's access to a repository they imported; None for the others.
    expires_at: datetime | None = None


@router.get("")
async def list_repositories(
    services: ServicesDep, request: Request, caller: CallerDep
) -> list[RepositoryListing]:
    """The repositories that can be searched and questioned, sorted by name.

    A demo key only sees the DEMO_REPOSITORIES, and the repositories its visitor
    imported.
    """
    async with services.session_factory() as session:
        summaries = await RepositoryCatalog(session).list_ready()
        own = (
            await VisitorAccessStore(session).repositories(caller.visitor_id)
            if caller.visitor_id is not None
            else {}
        )
    settings = request.app.state.settings
    listings: list[RepositoryListing] = []
    for summary in summaries:
        key = summary.repository.lower()
        if is_allowed(settings, caller.role, key):
            listings.append(RepositoryListing(**summary.model_dump()))
        elif key in own:
            listings.append(RepositoryListing(**summary.model_dump(), expires_at=own[key]))
    return listings


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
    ref = _parse(owner, name)
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


MAX_SUGGESTIONS = 6

Question = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
]


class Suggestions(BaseModel):
    """Suggested questions with answers generated in advance (no model call to serve)."""

    model_config = ConfigDict(frozen=True)

    repository: str
    # The commit the answers were generated from: the latest indexed one.
    commit_sha: str
    language: Language
    items: list[CachedAnswer]


class SuggestionsRequest(BaseModel):
    language: Language
    questions: list[Question] = Field(min_length=1, max_length=MAX_SUGGESTIONS)


@router.get(
    "/{owner}/{name}/suggestions",
    responses={404: {"description": "The repository has not been imported, or is still indexing."}},
)
async def get_suggestions(
    owner: str,
    name: str,
    services: ServicesDep,
    request: Request,
    caller: CallerDep,
    language: Language = "fr",
) -> Suggestions:
    """Suggested questions about the repository's latest snapshot, with their cached
    answers (empty if none were generated for it). Costs nothing to serve."""
    ref = _parse(owner, name)
    await ensure_repository_allowed(request, services, caller, ref)
    async with services.session_factory() as session:
        snapshot = await ChunkSearch(session).latest_ready_snapshot(ref.full_name)
        if snapshot is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, detail=str(RepositoryNotIndexedError.for_repository(ref))
            )
        items = await CachedAnswerStore(session).for_snapshot(snapshot.id, language)
    return Suggestions(
        repository=snapshot.repository,
        commit_sha=snapshot.commit_sha,
        language=language,
        items=items,
    )


@router.put(
    "/{owner}/{name}/suggestions",
    dependencies=[Depends(require_admin)],
    responses={
        403: {"description": "Admin key required."},
        409: {"description": "A new snapshot became ready meanwhile: try again."},
    },
)
async def set_suggestions(
    owner: str, name: str, body: SuggestionsRequest, services: ServicesDep, request: Request
) -> Suggestions:
    """Answer each question now (billed like POST /ask) and cache the answers for the
    repository's latest snapshot, replacing its suggestions in that language.

    All or nothing: if one answer fails, nothing is saved.
    """
    ref = _parse(owner, name)
    answers: list[tuple[str, Answer]] = []
    # One at a time: this is a rare admin task, and it must not take every slot.
    for question in body.questions:
        answers.append((question, await generate_answer(services, request, ref, question)))

    commits = {answer.commit_sha for _, answer in answers}
    async with services.session_factory.begin() as session:
        store = CachedAnswerStore(session)
        snapshot_id = (
            await store.snapshot_id(ref.full_name, commits.pop()) if len(commits) == 1 else None
        )
        if snapshot_id is None:
            # An import finished (or pruned the snapshot) between two answers.
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                detail="The repository changed while the answers were generated. Try again.",
            )
        await store.replace(snapshot_id, body.language, answers)
        items = await store.for_snapshot(snapshot_id, body.language)
    first = answers[0][1]
    return Suggestions(
        repository=first.repository,
        commit_sha=first.commit_sha,
        language=body.language,
        items=items,
    )


def _parse(owner: str, name: str) -> GitHubRepoRef:
    try:
        return parse_github_full_name(f"{owner}/{name}")
    except InvalidRepositoryUrlError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

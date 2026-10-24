"""Streamed answers (POST /ask/stream), on a real database, with fake models."""

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any

import httpx2 as httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request

from tests.generation_fakes import FakeAnswerModel
from tests.integration.test_search import SHA_NEW, AxisEmbedder, add_snapshot, vector
from tests.integration.test_usage import tracker, usage_rows
from uaw.api import ask as ask_api
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.generation.answerer import NO_SOURCES_MESSAGE, Answerer
from uaw.generation.claude import AnswerDelta, StreamEvent
from uaw.generation.errors import GenerationUnavailableError
from uaw.main import create_app
from uaw.retrieval.retriever import Retriever
from uaw.services import Services
from uaw.storage.models import BudgetReservationRow
from uaw.usage.meter import record_usage
from uaw.usage.tracker import UsageTracker

pytestmark = [pytest.mark.db, pytest.mark.anyio]

QUESTION = {"repository": "octo/demo", "question": "Where are tokens checked?"}
DRAFT = "Tokens are checked in auth [S1], see also [S3]."


def app_for(
    session_factory: async_sessionmaker[AsyncSession],
    model: FakeAnswerModel,
    *,
    usage: UsageTracker | None = None,
    **settings: Any,
) -> tuple[FastAPI, Services]:
    retriever = Retriever(session_factory, AxisEmbedder())
    services = Services(
        session_factory=session_factory,
        runner=None,
        retriever=retriever,
        answerer=Answerer(retriever, model, top_k=2),
        usage=usage,
    )
    app = create_app(Settings(_env_file=None, app_env="test", **settings))
    app.dependency_overrides[get_services] = lambda: services
    return app, services


def http(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


def parse(body: str) -> list[tuple[str, Any]]:
    events = []
    for block in body.split("\n\n"):
        if not block:
            continue
        fields = dict(line.split(": ", 1) for line in block.split("\n"))
        events.append((fields["event"], json.loads(fields["data"])))
    return events


@pytest.fixture
async def indexed(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            files={
                "src/auth.py": [vector((0, 1.0))],
                "src/util.py": [vector((0, 1.0), (1, 1.0))],
                "src/far.py": [vector((1, 1.0))],
            },
        )


async def reservations(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(BudgetReservationRow))
        ).one()[0]


async def test_sources_then_the_draft_then_the_checked_answer(
    indexed: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    app, _ = app_for(session_factory, FakeAnswerModel(DRAFT))

    async with http(app) as client:
        response = await client.post("/ask/stream", json=QUESTION)
        plain = await client.post("/ask", json=QUESTION)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "no-transform" in response.headers["cache-control"]
    events = parse(response.text)
    names = [name for name, _ in events]
    assert names[0] == "sources" and names[-1] == "done"
    assert set(names[1:-1]) == {"delta"} and len(names) > 3

    sources = events[0][1]
    assert sources["commit_sha"] == SHA_NEW
    assert [p["id"] for p in sources["passages"]] == ["S1", "S2"]
    assert [p["path"] for p in sources["passages"]] == ["src/auth.py", "src/util.py"]
    # Not known yet: whether a passage is cited comes with the answer.
    assert "cited" not in sources["passages"][0]

    # The draft is the model's text as written, invented citation included...
    assert "".join(data["text"] for name, data in events if name == "delta") == DRAFT
    # ...the final answer is checked, exactly as POST /ask returns it.
    done = events[-1][1]
    assert done["answer"] == "Tokens are checked in auth [S1], see also."
    assert done["trace"]["removed_citations"] == ["S3"]
    assert {k: v for k, v in done.items() if k != "trace"} == {
        k: v for k, v in plain.json().items() if k != "trace"
    }


async def test_errors_before_the_stream_are_http_errors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    model = FakeAnswerModel(DRAFT)
    app, _ = app_for(session_factory, model)

    async with http(app) as client:
        unknown = await client.post("/ask/stream", json=QUESTION)
        invalid = await client.post("/ask/stream", json={"repository": "o/r", "question": " "})

    assert unknown.status_code == 404
    assert unknown.headers["content-type"] == "application/json"
    assert invalid.status_code == 422
    assert model.calls == []


async def test_a_busy_server_refuses_before_streaming(
    indexed: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    app, _ = app_for(session_factory, FakeAnswerModel(DRAFT), max_concurrent_asks=1)

    with app.state.ask_limiter.slot():
        async with http(app) as client:
            response = await client.post("/ask/stream", json=QUESTION)

    assert response.status_code == 503
    assert response.headers["Retry-After"] == "5"


async def test_an_empty_repository_is_answered_without_the_model(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={})
    model = FakeAnswerModel(DRAFT)
    app, _ = app_for(session_factory, model)

    async with http(app) as client:
        response = await client.post("/ask/stream", json=QUESTION)

    events = parse(response.text)
    assert [name for name, _ in events] == ["sources", "done"]
    assert events[0][1]["passages"] == []
    assert events[1][1]["answer"] == NO_SOURCES_MESSAGE
    assert model.calls == []


class FailingModel(FakeAnswerModel):
    async def stream(self, system: str, user_message: str) -> AsyncIterator[StreamEvent]:
        yield AnswerDelta(text="Tokens are")
        raise GenerationUnavailableError("Claude is unavailable or rate limited. Try again later.")


async def test_a_failure_while_writing_is_an_error_event(
    indexed: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    app, _ = app_for(session_factory, FailingModel(DRAFT))

    async with http(app) as client:
        response = await client.post("/ask/stream", json=QUESTION)

    assert response.status_code == 200
    assert parse(response.text)[1:] == [
        ("delta", {"text": "Tokens are"}),
        (
            "error",
            {"status": 503, "detail": "Claude is unavailable or rate limited. Try again later."},
        ),
    ]


class BilledModel(FakeAnswerModel):
    async def stream(self, system: str, user_message: str) -> AsyncIterator[StreamEvent]:
        record_usage("anthropic", "fake-model", input_tokens=100, output_tokens=20)
        async for event in super().stream(system, user_message):
            yield event


async def test_usage_is_recorded_and_the_budget_applies(
    indexed: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    # Room for one reservation (12,000 tokens), not for a second once 120 are spent.
    budget = tracker(session_factory, anthropic=12_100)
    app, _ = app_for(session_factory, BilledModel(DRAFT), usage=budget)

    async with http(app) as client:
        first = await client.post("/ask/stream", json=QUESTION)
        second = await client.post("/ask/stream", json=QUESTION)

    assert parse(first.text)[-1][0] == "done"
    assert await usage_rows(session_factory) == [
        ("ask", "octo/demo", "anthropic", "fake-model", 1, 100, 20)
    ]
    assert await reservations(session_factory) == 0
    assert second.status_code == 429


class EndlessModel(FakeAnswerModel):
    """Writes a little, then waits forever; bills what it wrote when stopped."""

    def __init__(self) -> None:
        super().__init__(DRAFT)
        self.stopped = asyncio.Event()

    async def stream(self, system: str, user_message: str) -> AsyncIterator[StreamEvent]:
        try:
            yield AnswerDelta(text="Tokens are")
            await asyncio.Event().wait()
        finally:
            record_usage("anthropic", "fake-model", input_tokens=100, output_tokens=3)
            self.stopped.set()


async def test_a_client_that_leaves_stops_the_answer_and_frees_its_limits(
    indexed: None, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    model = EndlessModel()
    budget = tracker(session_factory, anthropic=100_000)
    app, services = app_for(session_factory, model, usage=budget, max_concurrent_asks=1)
    request = Request({"type": "http", "app": app, "headers": []})
    stream = ask_api._AnswerStream(
        services, request, GitHubRepoRef(owner="octo", name="demo"), "Where?"
    )

    events = stream.events(await stream.first())
    assert (await anext(events)).startswith("event: sources")
    assert (await anext(events)).startswith("event: delta")
    assert await reservations(session_factory) == 1
    # What the response does when the connection is lost.
    await events.aclose()
    await asyncio.wait_for(model.stopped.wait(), timeout=5)
    running = set(ask_api._running)
    if running:  # cancelled tasks: wait for them to finish, without raising
        await asyncio.wait(running, timeout=5)

    assert await usage_rows(session_factory) == [
        ("ask", "octo/demo", "anthropic", "fake-model", 1, 100, 3)
    ]
    assert await reservations(session_factory) == 0
    with app.state.ask_limiter.slot():  # the only slot is free again
        pass

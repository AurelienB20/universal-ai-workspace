"""Token usage recording and daily budgets, on a real database."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

import httpx2 as httpx
import pytest
from sqlalchemy import insert, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.generation_fakes import FakeAnswerModel
from tests.integration.test_search import AxisEmbedder, add_snapshot, vector
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.generation.answerer import Answerer
from uaw.generation.claude import Generation
from uaw.ingestion.runner import IngestionRunner
from uaw.main import create_app
from uaw.retrieval.retriever import Retriever
from uaw.services import Services
from uaw.storage.models import BudgetReservationRow, UsageRecordRow
from uaw.storage.usage import UsageStore
from uaw.usage.meter import record_usage
from uaw.usage.tracker import BUSY_RETRY_AFTER_SECONDS, BudgetExceededError, UsageTracker

pytestmark = [pytest.mark.db, pytest.mark.anyio]

NOW = datetime(2026, 10, 23, 22, 0, tzinfo=UTC)


def tracker(
    session_factory: async_sessionmaker[AsyncSession], *, voyage: int = 0, anthropic: int = 0
) -> UsageTracker:
    return UsageTracker(
        session_factory,
        daily_budgets={"voyage": voyage, "anthropic": anthropic},
        clock=lambda: NOW,
    )


async def add_usage(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    provider: str,
    tokens: int,
    created_at: datetime = NOW,
) -> None:
    async with session_factory.begin() as session:
        await session.execute(
            insert(UsageRecordRow).values(
                id=uuid.uuid4(),
                created_at=created_at,
                operation="ask",
                repository="octo/demo",
                provider=provider,
                model="m",
                requests=1,
                input_tokens=tokens,
                output_tokens=0,
            )
        )


async def usage_rows(session_factory: async_sessionmaker[AsyncSession]) -> list[tuple[object, ...]]:
    async with session_factory() as session:
        result = await session.execute(
            select(
                UsageRecordRow.operation,
                UsageRecordRow.repository,
                UsageRecordRow.provider,
                UsageRecordRow.model,
                UsageRecordRow.requests,
                UsageRecordRow.input_tokens,
                UsageRecordRow.output_tokens,
            ).order_by(UsageRecordRow.provider)
        )
        return [tuple(row) for row in result]


async def test_usage_is_saved_even_when_the_operation_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    with pytest.raises(RuntimeError):
        async with tracker(session_factory).track("ask", "octo/demo"):
            record_usage("voyage", "voyage-code-3", input_tokens=7)
            record_usage("anthropic", "claude-opus-5-5", input_tokens=100, output_tokens=20)
            raise RuntimeError("the model call failed after being billed")

    assert await usage_rows(session_factory) == [
        ("ask", "octo/demo", "anthropic", "claude-opus-5-5", 1, 100, 20),
        ("ask", "octo/demo", "voyage", "voyage-code-3", 1, 7, 0),
    ]


async def test_spent_budget_refuses_until_midnight_utc(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_usage(session_factory, provider="anthropic", tokens=600)
    await add_usage(session_factory, provider="anthropic", tokens=400)

    with pytest.raises(BudgetExceededError) as exc_info:
        await tracker(session_factory, anthropic=1000).ensure_within_budget("voyage", "anthropic")

    assert exc_info.value.provider == "anthropic"
    assert exc_info.value.retry_after_seconds == 2 * 3600 + 1


async def test_budget_counts_today_and_the_right_provider_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_usage(
        session_factory, provider="anthropic", tokens=5000, created_at=NOW - timedelta(days=1)
    )
    await add_usage(session_factory, provider="voyage", tokens=5000)

    await tracker(session_factory, anthropic=1000).ensure_within_budget("anthropic")


async def test_zero_budget_means_unlimited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_usage(session_factory, provider="voyage", tokens=10**9)

    await tracker(session_factory).ensure_within_budget("voyage", "anthropic")


class BilledModel(FakeAnswerModel):
    async def generate(self, system: str, user_message: str) -> Generation:
        record_usage("anthropic", "fake-model", input_tokens=100, output_tokens=20)
        return await super().generate(system, user_message)


def ask_client(
    session_factory: async_sessionmaker[AsyncSession], usage: UsageTracker
) -> httpx.AsyncClient:
    retriever = Retriever(session_factory, AxisEmbedder())
    services = Services(
        session_factory=session_factory,
        runner=None,
        retriever=retriever,
        answerer=Answerer(retriever, BilledModel("Answer [S1]."), top_k=2),
        usage=usage,
    )
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_services] = lambda: services
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


async def test_ask_records_usage_then_is_refused_once_the_budget_is_spent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={"src/auth.py": [vector((0, 1.0))]})
    question = {"repository": "octo/demo", "question": "Where?"}
    # Each question reserves ASK_RESERVED_LLM_TOKENS (12,000 by default) before it
    # starts: the first fits, the second no longer does once 120 tokens are spent.
    budget = tracker(session_factory, anthropic=12_100)

    async with ask_client(session_factory, budget) as client:
        first = await client.post("/ask", json=question)
        second = await client.post("/ask", json=question)

    assert first.status_code == 200
    assert await usage_rows(session_factory) == [
        ("ask", "octo/demo", "anthropic", "fake-model", 1, 100, 20)
    ]
    assert second.status_code == 429
    assert "daily usage limit" in second.json()["detail"]
    assert int(second.headers["Retry-After"]) > 0


class BilledPipeline:
    async def run(self, job_id: uuid.UUID, ref: GitHubRepoRef) -> None:
        record_usage("voyage", "voyage-code-3", input_tokens=500)
        record_usage("voyage", "voyage-code-3", input_tokens=300)


async def test_background_imports_record_their_usage(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    runner = IngestionRunner(BilledPipeline(), max_concurrent=1, usage=tracker(session_factory))

    runner.submit(uuid.uuid4(), GitHubRepoRef(owner="octo", name="demo"))
    await runner.wait_idle()

    assert await usage_rows(session_factory) == [
        ("import", "octo/demo", "voyage", "voyage-code-3", 2, 800, 0)
    ]


async def test_readiness_checks_the_database(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    services = Services(session_factory=session_factory, runner=None, retriever=None, answerer=None)
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_services] = lambda: services
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "database": "ok"}


async def reserved_now(session_factory: async_sessionmaker[AsyncSession], provider: str) -> int:
    async with session_factory() as session:
        return await UsageStore(session).reserved_tokens(provider, NOW)  # type: ignore[arg-type]


async def test_simultaneous_reservations_never_exceed_the_budget(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    # Room for exactly 3 questions of 1,000 tokens: 5 arrive at the same time.
    usage = tracker(session_factory, anthropic=3_000)
    release = asyncio.Event()
    admitted = 0

    async def question() -> str:
        nonlocal admitted
        try:
            async with usage.reserve({"anthropic": 1_000}):
                admitted += 1
                await release.wait()  # still running when the others check
            return "answered"
        except BudgetExceededError as exc:
            return f"refused {exc.retry_after_seconds}s"

    tasks = [asyncio.create_task(question()) for _ in range(5)]
    async with asyncio.timeout(10):
        while admitted < 3 or sum(task.done() for task in tasks) < 2:
            await asyncio.sleep(0.01)
    assert await reserved_now(session_factory, "anthropic") == 3_000
    release.set()
    results = await asyncio.gather(*tasks)

    # Refused for a short while only: the budget is held, not spent.
    assert sorted(results) == ["answered"] * 3 + [f"refused {BUSY_RETRY_AFTER_SECONDS}s"] * 2
    assert await reserved_now(session_factory, "anthropic") == 0


async def test_reservation_is_released_when_the_operation_fails(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    usage = tracker(session_factory, anthropic=1_000)

    with pytest.raises(RuntimeError):
        async with usage.reserve({"anthropic": 1_000}):
            raise RuntimeError("model unavailable")

    assert await reserved_now(session_factory, "anthropic") == 0
    async with usage.reserve({"anthropic": 1_000}):  # the whole budget is free again
        pass


async def test_reservation_that_no_longer_fits_the_spent_budget_waits_for_midnight(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_usage(session_factory, provider="anthropic", tokens=2_500)

    with pytest.raises(BudgetExceededError) as exc_info:
        async with tracker(session_factory, anthropic=3_000).reserve({"anthropic": 1_000}):
            pass

    assert exc_info.value.retry_after_seconds == 2 * 3600 + 1
    assert "daily usage limit" in str(exc_info.value)


async def test_refusal_on_one_provider_keeps_no_reservation_on_the_other(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_usage(session_factory, provider="voyage", tokens=1_000)

    with pytest.raises(BudgetExceededError):
        usage = tracker(session_factory, voyage=1_000, anthropic=10_000)
        async with usage.reserve({"anthropic": 1_000, "voyage": 10}):
            pass

    assert await reserved_now(session_factory, "anthropic") == 0


async def test_expired_reservations_are_ignored_then_cleaned_up(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        # Left by a process that crashed mid-question.
        await UsageStore(session).add_reservation(
            "anthropic", 1_000, expires_at=NOW - timedelta(seconds=1)
        )

    async with tracker(session_factory, anthropic=1_000).reserve({"anthropic": 1_000}):
        pass

    async with session_factory() as session:
        assert (await session.execute(select(BudgetReservationRow))).all() == []


async def test_no_budget_means_no_reservation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with tracker(session_factory).reserve({"anthropic": 10**9}):
        assert await reserved_now(session_factory, "anthropic") == 0

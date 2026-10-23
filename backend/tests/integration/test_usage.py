"""Token usage recording and daily budgets, on a real database."""

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
from uaw.storage.models import UsageRecordRow
from uaw.usage.meter import record_usage
from uaw.usage.tracker import BudgetExceededError, UsageTracker

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

    async with ask_client(session_factory, tracker(session_factory, anthropic=120)) as client:
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

"""Imports by visitors of the public demo, through the HTTP API, with fake GitHub and
Voyage services."""

import uuid
from collections.abc import AsyncIterator, Callable
from typing import Any

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.fakes import FakeEmbedder, FakeSource
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.connector import ImportLimits
from uaw.connectors.github.url import GitHubRepoRef
from uaw.ingestion.pipeline import ImportPolicy, IngestionPipeline
from uaw.ingestion.runner import IngestionRunner
from uaw.main import create_app
from uaw.services import Services
from uaw.storage.jobs import JobStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

ANN = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB = uuid.UUID("22222222-2222-4222-8222-222222222222")
CAROL = uuid.UUID("33333333-3333-4333-8333-333333333333")
ADMIN = {"X-API-Key": "admin-key"}


def visitor(visitor_id: uuid.UUID) -> dict[str, str]:
    return {"X-API-Key": "demo-key", "X-Visitor-Id": str(visitor_id)}


def url(name: str) -> dict[str, str]:
    return {"url": f"https://github.com/octo/{name}"}


class Demo:
    """The API with public imports enabled, and the fakes behind it."""

    def __init__(self, http: httpx.AsyncClient, runner: IngestionRunner, source: FakeSource):
        self.http = http
        self.runner = runner
        self.source = source

    async def import_as(self, visitor_id: uuid.UUID, name: str = "demo") -> httpx.Response:
        return await self.http.post("/imports", json=url(name), headers=visitor(visitor_id))

    async def listed(self, visitor_id: uuid.UUID) -> list[str]:
        response = await self.http.get("/repositories", headers=visitor(visitor_id))
        assert response.status_code == 200
        return [item["repository"] for item in response.json()]


DemoFactory = Callable[..., Any]


@pytest.fixture
async def make_demo(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[DemoFactory]:
    runners: list[IngestionRunner] = []
    clients: list[httpx.AsyncClient] = []

    async def make(source: FakeSource | None = None, **overrides: Any) -> Demo:
        # Every test client shares one address: the per-address limit has its own test.
        overrides.setdefault("rate_limit_visitor_imports_per_day", 0)
        settings = Settings(
            _env_file=None,
            app_env="test",
            api_key=SecretStr("admin-key"),
            demo_api_key=SecretStr("demo-key"),
            public_imports_enabled=True,
            **overrides,
        )
        source = source or FakeSource()
        pipeline = IngestionPipeline(session_factory, source, FakeEmbedder())
        runner = IngestionRunner(
            pipeline,
            max_concurrent=2,
            visitor_policy=ImportPolicy(
                limits=ImportLimits.for_visitors(settings),
                max_embedding_tokens=settings.visitor_max_import_tokens,
            ),
        )
        app = create_app(settings)
        services = Services(
            session_factory=session_factory, runner=runner, retriever=None, answerer=None
        )
        app.dependency_overrides[get_services] = lambda: services
        http = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")
        runners.append(runner)
        clients.append(http)
        return Demo(http, runner, source)

    yield make
    for runner in runners:
        await runner.shutdown()
    for http in clients:
        await http.aclose()


async def test_a_visitor_imports_a_repository_only_they_can_read(make_demo: DemoFactory) -> None:
    demo = await make_demo()

    response = await demo.import_as(ANN)

    assert response.status_code == 202
    job = response.json()
    await demo.runner.wait_idle()
    # Imported under the visitor limits.
    assert demo.source.limits == [ImportLimits.for_visitors(Settings(_env_file=None))]
    polled = await demo.http.get(f"/imports/{job['id']}", headers=visitor(ANN))
    assert polled.json()["status"] == "succeeded"
    assert await demo.listed(ANN) == ["Octo/Demo"]

    # Another visitor sees neither the repository nor the import.
    assert await demo.listed(BOB) == []
    hidden = await demo.http.get(f"/imports/{job['id']}", headers=visitor(BOB))
    assert hidden.status_code == 404
    asked = await demo.http.post(
        "/search", json={"repository": "octo/demo", "query": "q"}, headers=visitor(BOB)
    )
    assert asked.status_code == 404


async def test_an_indexed_repository_is_shared_without_a_new_import(
    make_demo: DemoFactory,
) -> None:
    demo = await make_demo(visitor_imports_per_visitor_per_day=1)
    first = await demo.import_as(ANN)
    await demo.runner.wait_idle()

    again = await demo.import_as(BOB)

    assert again.status_code == 200
    assert again.json()["id"] == first.json()["id"]
    assert len(demo.source.fetched) == 1
    assert await demo.listed(BOB) == ["Octo/Demo"]
    # Free: Bob's daily quota (1) is still there.
    assert (await demo.import_as(BOB, "other")).status_code == 202
    await demo.runner.wait_idle()


async def test_an_admin_import_is_shared_the_same_way(make_demo: DemoFactory) -> None:
    demo = await make_demo()
    await demo.http.post("/imports", json=url("demo"), headers=ADMIN)
    await demo.runner.wait_idle()

    response = await demo.import_as(ANN)

    assert response.status_code == 200
    assert demo.source.limits == [None]  # only the admin's import ran
    assert await demo.listed(ANN) == ["Octo/Demo"]


async def test_each_visitor_has_a_daily_quota(make_demo: DemoFactory) -> None:
    demo = await make_demo(visitor_imports_per_visitor_per_day=2)
    for name in ("one", "two"):
        assert (await demo.import_as(ANN, name)).status_code == 202
        await demo.runner.wait_idle()

    refused = await demo.import_as(ANN, "three")

    assert refused.status_code == 429
    assert refused.json()["detail"] == "You can import 2 repositories a day. Try again tomorrow."
    assert 0 < int(refused.headers["retry-after"]) <= 86_400
    assert (await demo.import_as(BOB, "three")).status_code == 202
    await demo.runner.wait_idle()


async def test_the_demo_has_a_daily_quota(make_demo: DemoFactory) -> None:
    demo = await make_demo(visitor_imports_per_day=2)
    for visitor_id, name in ((ANN, "one"), (BOB, "two")):
        assert (await demo.import_as(visitor_id, name)).status_code == 202
        await demo.runner.wait_idle()

    refused = await demo.import_as(CAROL, "three")

    assert refused.status_code == 429
    assert refused.json()["detail"] == (
        "The demo has reached its import limit for today. Try again tomorrow."
    )
    # The admin is not counted, nor limited.
    assert (await demo.http.post("/imports", json=url("three"), headers=ADMIN)).status_code == 202
    await demo.runner.wait_idle()


async def test_each_address_has_a_daily_limit(make_demo: DemoFactory) -> None:
    demo = await make_demo(rate_limit_visitor_imports_per_day=1)
    assert (await demo.import_as(ANN, "one")).status_code == 202
    await demo.runner.wait_idle()

    # A new visitor id from the same address does not reset it.
    refused = await demo.import_as(BOB, "two")

    assert refused.status_code == 429
    assert refused.json()["detail"] == "Too many requests. Try again later."


async def test_a_full_queue_refuses_new_imports(
    make_demo: DemoFactory, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    demo = await make_demo(visitor_import_queue=0)
    async with session_factory.begin() as session:
        await JobStore(session).create_or_get_active("octo/running", BOB)

    refused = await demo.import_as(ANN)

    assert refused.status_code == 503
    assert refused.headers["retry-after"] == "60"
    assert await demo.listed(ANN) == []


async def test_a_repository_too_costly_to_index_is_refused(make_demo: DemoFactory) -> None:
    demo = await make_demo(visitor_max_import_tokens=10)

    job = (await demo.import_as(ANN)).json()
    await demo.runner.wait_idle()

    polled = (await demo.http.get(f"/imports/{job['id']}", headers=visitor(ANN))).json()
    assert polled["status"] == "failed"
    assert polled["error"].startswith("This repository is too large for the public demo:")
    assert polled["embedded_count"] == 0
    assert await demo.listed(ANN) == []


async def test_a_renamed_repository_stays_readable(make_demo: DemoFactory) -> None:
    demo = await make_demo(FakeSource(canonical=GitHubRepoRef(owner="octo", name="renamed")))

    await demo.import_as(ANN, "old-name")
    await demo.runner.wait_idle()

    assert await demo.listed(ANN) == ["octo/renamed"]


async def test_a_visitor_id_is_required_to_import(make_demo: DemoFactory) -> None:
    demo = await make_demo()

    response = await demo.http.post("/imports", json=url("demo"), headers={"X-API-Key": "demo-key"})

    assert response.status_code == 422
    assert response.json()["detail"] == "An X-Visitor-Id header is required."

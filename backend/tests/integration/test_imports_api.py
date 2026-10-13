"""End-to-end import through the HTTP API, with fake GitHub and Voyage services."""

import uuid
from collections.abc import AsyncIterator

import httpx2 as httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.fakes import FakeEmbedder, FakeSource
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.ingestion.pipeline import IngestionPipeline
from uaw.ingestion.runner import IngestionRunner
from uaw.main import create_app
from uaw.services import Services

pytestmark = [pytest.mark.db, pytest.mark.anyio]


@pytest.fixture
def runner(session_factory: async_sessionmaker[AsyncSession]) -> IngestionRunner:
    pipeline = IngestionPipeline(session_factory, FakeSource(), FakeEmbedder())
    return IngestionRunner(pipeline, max_concurrent=2)


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], runner: IngestionRunner
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(_env_file=None, app_env="test"))
    services = Services(session_factory=session_factory, runner=runner, retriever=None)
    app.dependency_overrides[get_services] = lambda: services
    # ASGITransport runs the app in this event loop, like the database fixtures.
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http
    await runner.shutdown()


async def test_import_runs_in_background_and_can_be_polled(
    client: httpx.AsyncClient, runner: IngestionRunner
) -> None:
    response = await client.post("/imports", json={"url": "https://github.com/octo/demo"})

    assert response.status_code == 202
    job = response.json()
    assert job["status"] == "queued"
    assert response.headers["location"] == f"/imports/{job['id']}"

    await runner.wait_idle()
    polled = (await client.get(f"/imports/{job['id']}")).json()
    assert polled["status"] == "succeeded"
    assert polled["repository"] == "Octo/Demo"
    assert polled["chunks_count"] == polled["embedded_count"] > 0
    assert polled["snapshot_id"] is not None


async def test_duplicate_request_returns_the_active_job(
    client: httpx.AsyncClient, runner: IngestionRunner
) -> None:
    first = await client.post("/imports", json={"url": "https://github.com/octo/demo"})
    second = await client.post("/imports", json={"url": "https://github.com/Octo/Demo.git"})

    assert (first.status_code, second.status_code) == (202, 200)
    assert second.json()["id"] == first.json()["id"]
    await runner.wait_idle()


async def test_unknown_job_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get(f"/imports/{uuid.uuid4()}")

    assert response.status_code == 404

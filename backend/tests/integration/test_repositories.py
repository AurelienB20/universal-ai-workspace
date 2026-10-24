"""GET /repositories against PostgreSQL."""

from collections.abc import AsyncIterator

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_search import SHA_NEW, SHA_OLD, add_snapshot, vector
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.main import create_app
from uaw.services import Services
from uaw.storage.jobs import JobStore
from uaw.storage.models import ChunkRow, RepositoryRow, UsageRecordRow
from uaw.storage.usage import UsageStore
from uaw.usage.meter import ModelUsage

pytestmark = [pytest.mark.db, pytest.mark.anyio]

ALPHA = GitHubRepoRef(owner="Octo", name="Alpha")
BETA = GitHubRepoRef(owner="octo", name="beta")
GAMMA = GitHubRepoRef(owner="octo", name="gamma")


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        api_key=SecretStr("admin-key"),
        demo_api_key=SecretStr("demo-key"),
        demo_repositories="octo/alpha",
    )
    app = create_app(settings)
    services = Services(session_factory=session_factory, runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def add_repositories(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory.begin() as session:
        # Two ready snapshots: the newest one is listed.
        await add_snapshot(
            session, repository=ALPHA, sha=SHA_OLD, files={"a.py": [vector((0, 1.0))]}
        )
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            repository=ALPHA,
            sha=SHA_NEW,
            files={"a.py": [vector((0, 1.0))], "b.py": [vector((1, 1.0)), vector((2, 1.0))]},
        )
        await add_snapshot(session, repository=BETA, files={"c.py": [vector((0, 1.0))]})
        # Still indexing: not searchable, so not listed.
        await add_snapshot(
            session, repository=GAMMA, files={"d.py": [vector((0, 1.0))]}, ready=False
        )


async def test_admin_sees_every_searchable_repository(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_repositories(session_factory)

    response = await client.get("/repositories", headers={"X-API-Key": "admin-key"})

    assert response.status_code == 200
    body = response.json()
    assert [item["repository"] for item in body] == ["Octo/Alpha", "octo/beta"]
    alpha = body[0]
    assert alpha["commit_sha"] == SHA_NEW
    assert alpha["default_branch"] == "main"
    assert (alpha["documents_count"], alpha["chunks_count"]) == (2, 3)
    assert alpha["indexed_at"]


async def test_demo_key_sees_only_the_allowlist(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_repositories(session_factory)

    response = await client.get("/repositories", headers={"X-API-Key": "demo-key"})

    assert response.status_code == 200
    assert [item["repository"] for item in response.json()] == ["Octo/Alpha"]


async def test_empty_database_lists_nothing(client: httpx.AsyncClient) -> None:
    response = await client.get("/repositories", headers={"X-API-Key": "admin-key"})

    assert response.status_code == 200
    assert response.json() == []


ADMIN = {"X-API-Key": "admin-key"}


async def count(session_factory: async_sessionmaker[AsyncSession], table: type[object]) -> int:
    async with session_factory() as session:
        return (await session.execute(select(func.count()).select_from(table))).scalar_one()


async def test_admin_deletes_a_repository_with_everything_in_it(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_repositories(session_factory)
    async with session_factory.begin() as session:
        await UsageStore(session).add(
            "ask", "Octo/Alpha", [ModelUsage("anthropic", "m", 1, 100, 20)]
        )

    response = await client.delete("/repositories/octo/ALPHA", headers=ADMIN)

    assert response.status_code == 204
    listed = await client.get("/repositories", headers=ADMIN)
    assert [item["repository"] for item in listed.json()] == ["octo/beta"]
    # Only beta's and gamma's chunks are left; the billed usage is kept.
    assert await count(session_factory, ChunkRow) == 2
    assert await count(session_factory, UsageRecordRow) == 1


async def test_deleting_during_an_import_is_refused(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_repositories(session_factory)
    async with session_factory.begin() as session:
        await JobStore(session).create_or_get_active("octo/alpha")

    response = await client.delete("/repositories/Octo/Alpha", headers=ADMIN)

    assert response.status_code == 409
    assert await count(session_factory, RepositoryRow) == 3


async def test_deleting_an_unknown_repository_is_404(client: httpx.AsyncClient) -> None:
    response = await client.delete("/repositories/octo/nothing", headers=ADMIN)

    assert response.status_code == 404


async def test_demo_key_cannot_delete(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await add_repositories(session_factory)

    response = await client.delete("/repositories/octo/alpha", headers={"X-API-Key": "demo-key"})

    assert response.status_code == 403
    assert await count(session_factory, RepositoryRow) == 3


async def test_invalid_repository_name_is_422(client: httpx.AsyncClient) -> None:
    response = await client.delete("/repositories/not_an_owner/repo", headers=ADMIN)

    assert response.status_code == 422

"""Repositories imported by visitors of the public demo: readable by their visitor only."""

import uuid
from collections.abc import AsyncIterator
from datetime import datetime, timedelta

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_search import add_snapshot, vector
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.main import create_app
from uaw.services import Services
from uaw.storage.visitors import VisitorAccessStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

DEMO_REPO = GitHubRepoRef(owner="octo", name="demo")
MINE = GitHubRepoRef(owner="Ann", name="Mine")
THEIRS = GitHubRepoRef(owner="bob", name="theirs")
ANN = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB = uuid.UUID("22222222-2222-4222-8222-222222222222")
DAY = timedelta(hours=24)


def demo(visitor: uuid.UUID | None = None) -> dict[str, str]:
    headers = {"X-API-Key": "demo-key"}
    if visitor is not None:
        headers["X-Visitor-Id"] = str(visitor)
    return headers


ADMIN = {"X-API-Key": "admin-key"}


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    settings = Settings(
        _env_file=None,
        app_env="test",
        api_key=SecretStr("admin-key"),
        demo_api_key=SecretStr("demo-key"),
        demo_repositories="octo/demo",
        visitor_questions_per_day=2,
    )
    app = create_app(settings)
    # No providers: a request that passes the access check ends with a 503.
    services = Services(session_factory=session_factory, runner=None, retriever=None, answerer=None)
    app.dependency_overrides[get_services] = lambda: services
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


@pytest.fixture
async def repositories(session_factory: async_sessionmaker[AsyncSession]) -> None:
    async with session_factory.begin() as session:
        for ref in (DEMO_REPO, MINE, THEIRS):
            await add_snapshot(session, repository=ref, files={"a.py": [vector((0, 1.0))]})
        store = VisitorAccessStore(session)
        await store.grant(ANN, "ann/mine", DAY)
        await store.grant(BOB, "bob/theirs", DAY)


def names(response: httpx.Response) -> list[str]:
    assert response.status_code == 200
    return [item["repository"] for item in response.json()]


@pytest.mark.usefixtures("repositories")
async def test_a_visitor_lists_the_demo_and_their_own_repositories(
    client: httpx.AsyncClient,
) -> None:
    response = await client.get("/repositories", headers=demo(ANN))

    assert names(response) == ["Ann/Mine", "octo/demo"]
    mine, shared = response.json()
    expires_at = datetime.fromisoformat(mine["expires_at"])
    assert timedelta(hours=23) < expires_at - datetime.now(expires_at.tzinfo) <= DAY
    assert shared["expires_at"] is None


@pytest.mark.usefixtures("repositories")
async def test_without_a_visitor_id_only_the_demo_is_listed(client: httpx.AsyncClient) -> None:
    assert names(await client.get("/repositories", headers=demo())) == ["octo/demo"]


@pytest.mark.usefixtures("repositories")
async def test_the_admin_lists_everything_without_expiry(client: httpx.AsyncClient) -> None:
    response = await client.get("/repositories", headers=ADMIN)

    assert names(response) == ["Ann/Mine", "bob/theirs", "octo/demo"]
    assert all(item["expires_at"] is None for item in response.json())


@pytest.mark.usefixtures("repositories")
@pytest.mark.parametrize(
    ("path", "body"),
    [("/ask", {"question": "Where?"}), ("/search", {"query": "Where?"})],
)
async def test_a_visitor_questions_their_own_repository_only(
    client: httpx.AsyncClient, path: str, body: dict[str, str]
) -> None:
    # 503: past the access check (no provider is configured in these tests).
    mine = await client.post(path, json={**body, "repository": "ann/MINE"}, headers=demo(ANN))
    assert mine.status_code == 503

    theirs = await client.post(path, json={**body, "repository": "bob/theirs"}, headers=demo(ANN))
    assert theirs.status_code == 404
    # The same answer as for a repository that was never imported.
    assert theirs.json()["detail"] == (
        "bob/theirs has not been imported yet, or its import is not finished."
    )


@pytest.mark.usefixtures("repositories")
async def test_suggestions_follow_the_same_rule(client: httpx.AsyncClient) -> None:
    mine = await client.get("/repositories/Ann/Mine/suggestions", headers=demo(ANN))
    theirs = await client.get("/repositories/bob/theirs/suggestions", headers=demo(ANN))

    assert mine.status_code == 200
    assert theirs.status_code == 404


async def test_an_expired_access_is_gone(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, repository=MINE, files={"a.py": [vector((0, 1.0))]})
        await VisitorAccessStore(session).grant(ANN, "ann/mine", timedelta(seconds=-1))

    assert names(await client.get("/repositories", headers=demo(ANN))) == []
    response = await client.post(
        "/search", json={"repository": "ann/mine", "query": "q"}, headers=demo(ANN)
    )
    assert response.status_code == 404


async def test_granting_again_extends_but_never_shortens(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        store = VisitorAccessStore(session)
        await store.grant(ANN, "Ann/Mine", DAY)
        first = (await store.repositories(ANN))["ann/mine"]
        await store.grant(ANN, "ann/mine", timedelta(hours=1))
        assert (await store.repositories(ANN))["ann/mine"] == first
        await store.grant(ANN, "ann/mine", 2 * DAY)
        assert (await store.repositories(ANN))["ann/mine"] == first + DAY


@pytest.mark.usefixtures("repositories")
async def test_questions_about_their_own_repositories_have_a_daily_quota(
    client: httpx.AsyncClient,
) -> None:
    async def ask(repository: str, visitor_id: uuid.UUID = ANN) -> httpx.Response:
        body = {"repository": repository, "question": "Where?"}
        return await client.post("/ask", json=body, headers=demo(visitor_id))

    # 503: past the checks (no provider is configured in these tests).
    assert [(await ask("ann/mine")).status_code for _ in range(2)] == [503, 503]
    refused = await ask("ann/mine")
    assert refused.status_code == 429
    assert refused.json()["detail"] == (
        "You can ask 2 questions a day about the repositories you imported. Try again tomorrow."
    )
    # Questions about the demo's repositories are not counted, nor other visitors'.
    assert (await ask("octo/demo")).status_code == 503
    assert (await ask("bob/theirs", BOB)).status_code == 503

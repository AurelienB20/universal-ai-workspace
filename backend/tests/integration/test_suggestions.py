"""Suggested questions with cached answers, on a real database, with a fake model."""

from collections.abc import AsyncIterator

import httpx2 as httpx
import pytest
from pydantic import SecretStr
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.generation_fakes import FakeAnswerModel
from tests.integration.test_search import SHA_NEW, SHA_OLD, AxisEmbedder, add_snapshot, vector
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.url import GitHubRepoRef
from uaw.generation.answerer import Answerer
from uaw.generation.claude import Generation
from uaw.generation.errors import GenerationUnavailableError
from uaw.main import create_app
from uaw.retrieval.retriever import Retriever
from uaw.services import Services
from uaw.storage.models import CachedAnswerRow
from uaw.storage.store import SnapshotStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

ADMIN = {"X-API-Key": "admin-key"}
DEMO = {"X-API-Key": "demo-key"}
URL = "/repositories/octo/demo/suggestions"


class FlakyModel(FakeAnswerModel):
    """Fails on the given call (1-based), like a provider outage mid-way."""

    def __init__(self, answer: str, *, fail_on: int) -> None:
        super().__init__(answer)
        self.fail_on = fail_on

    async def generate(self, system: str, user_message: str) -> Generation:
        if len(self.calls) + 1 == self.fail_on:
            self.calls.append((system, user_message))
            raise GenerationUnavailableError("The answer service is unavailable.")
        return await super().generate(system, user_message)


def client_for(
    session_factory: async_sessionmaker[AsyncSession], model: FakeAnswerModel
) -> httpx.AsyncClient:
    retriever = Retriever(session_factory, AxisEmbedder())
    services = Services(
        session_factory=session_factory,
        runner=None,
        retriever=retriever,
        answerer=Answerer(retriever, model, top_k=2),
    )
    settings = Settings(
        _env_file=None,
        app_env="test",
        api_key=SecretStr("admin-key"),
        demo_api_key=SecretStr("demo-key"),
        demo_repositories="octo/demo",
    )
    app = create_app(settings)
    app.dependency_overrides[get_services] = lambda: services
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def model() -> FakeAnswerModel:
    return FakeAnswerModel("Tokens are checked in auth [S1].")


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], model: FakeAnswerModel
) -> AsyncIterator[httpx.AsyncClient]:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={"src/auth.py": [vector((0, 1.0))]})
    async with client_for(session_factory, model) as http:
        yield http


async def cached_rows(session_factory: async_sessionmaker[AsyncSession]) -> int:
    async with session_factory() as session:
        return (
            await session.execute(select(func.count()).select_from(CachedAnswerRow))
        ).scalar_one()


async def test_answers_are_generated_once_then_served_without_the_model(
    client: httpx.AsyncClient, model: FakeAnswerModel
) -> None:
    questions = ["Where are tokens checked?", "  How do signatures work?  "]

    created = await client.put(URL, json={"language": "en", "questions": questions}, headers=ADMIN)

    assert created.status_code == 200
    assert len(model.calls) == 2
    for _ in range(3):
        served = await client.get(URL, params={"language": "en"}, headers=DEMO)
        assert served.status_code == 200
    assert len(model.calls) == 2  # serving costs nothing

    body = served.json()
    assert body == created.json()
    assert body["repository"] == "octo/demo"
    assert body["commit_sha"] == SHA_NEW
    assert [item["question"] for item in body["items"]] == [
        "Where are tokens checked?",
        "How do signatures work?",
    ]
    item = body["items"][0]
    assert item["answer"]["model"] == "fake-model"
    assert item["answer"]["citations"][0]["path"] == "src/auth.py"
    assert item["generated_at"]


async def test_suggestions_are_replaced_per_language(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(URL, json={"language": "fr", "questions": ["Un ?", "Deux ?"]}, headers=ADMIN)
    await client.put(URL, json={"language": "en", "questions": ["One?"]}, headers=ADMIN)
    await client.put(URL, json={"language": "fr", "questions": ["Trois ?"]}, headers=ADMIN)

    french = (await client.get(URL, params={"language": "fr"}, headers=DEMO)).json()
    english = (await client.get(URL, params={"language": "en"}, headers=DEMO)).json()

    assert [item["question"] for item in french["items"]] == ["Trois ?"]
    assert [item["question"] for item in english["items"]] == ["One?"]
    assert await cached_rows(session_factory) == 2


async def test_no_suggestions_yet_is_an_empty_list(client: httpx.AsyncClient) -> None:
    response = await client.get(URL, headers=DEMO)

    assert response.status_code == 200
    assert response.json()["items"] == []
    assert response.json()["language"] == "fr"


async def test_a_new_snapshot_starts_without_suggestions(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(URL, json={"language": "fr", "questions": ["Où ?"]}, headers=ADMIN)
    # A newer commit is imported: the cached answers describe the old one.
    async with session_factory.begin() as session:
        await add_snapshot(session, sha="c" * 40, files={"src/auth.py": [vector((0, 1.0))]})

    response = await client.get(URL, headers=DEMO)

    assert response.json()["commit_sha"] == "c" * 40
    assert response.json()["items"] == []


async def test_deleting_the_snapshot_deletes_its_cached_answers(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    await client.put(URL, json={"language": "fr", "questions": ["Où ?"]}, headers=ADMIN)

    async with session_factory.begin() as session:
        snapshot_id = await session.scalar(select(CachedAnswerRow.snapshot_id))
        assert snapshot_id is not None
        await SnapshotStore(session).delete_snapshot(snapshot_id)

    assert await cached_rows(session_factory) == 0


async def test_a_failure_mid_way_saves_nothing(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={"src/auth.py": [vector((0, 1.0))]})
    model = FlakyModel("Answer [S1].", fail_on=2)

    async with client_for(session_factory, model) as http:
        await http.put(URL, json={"language": "fr", "questions": ["Ancienne ?"]}, headers=ADMIN)
        response = await http.put(
            URL, json={"language": "fr", "questions": ["Un ?", "Deux ?", "Trois ?"]}, headers=ADMIN
        )
        kept = (await http.get(URL, headers=DEMO)).json()

    assert response.status_code == 503
    # The previous suggestions are still served, untouched.
    assert [item["question"] for item in kept["items"]] == ["Ancienne ?"]


async def test_demo_key_cannot_generate(client: httpx.AsyncClient, model: FakeAnswerModel) -> None:
    response = await client.put(URL, json={"language": "fr", "questions": ["Où ?"]}, headers=DEMO)

    assert response.status_code == 403
    assert model.calls == []


async def test_demo_key_cannot_read_other_repositories(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            repository=GitHubRepoRef(owner="octo", name="secret"),
            sha=SHA_OLD,
            files={"a.py": [vector((0, 1.0))]},
        )

    response = await client.get("/repositories/octo/secret/suggestions", headers=DEMO)

    assert response.status_code == 404


@pytest.mark.parametrize(
    "body",
    [
        {"language": "fr", "questions": []},
        {"language": "fr", "questions": ["   "]},
        {"language": "fr", "questions": ["Q ?"] * 7},
        {"language": "de", "questions": ["Q?"]},
        {"language": "fr", "questions": ["x" * 2001]},
    ],
)
async def test_invalid_requests_are_rejected_before_any_model_call(
    client: httpx.AsyncClient, model: FakeAnswerModel, body: dict[str, object]
) -> None:
    response = await client.put(URL, json=body, headers=ADMIN)

    assert response.status_code == 422
    assert model.calls == []


async def test_unknown_repository_is_404(client: httpx.AsyncClient) -> None:
    response = await client.get("/repositories/octo/nothing/suggestions", headers=ADMIN)

    assert response.status_code == 404

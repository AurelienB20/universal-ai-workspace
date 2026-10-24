"""Question answering through the HTTP API, on a real database, with a fake model."""

from collections.abc import AsyncIterator

import httpx2 as httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.generation_fakes import FakeAnswerModel
from tests.integration.test_search import SHA_NEW, AxisEmbedder, add_snapshot, vector
from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.generation.answerer import NO_SOURCES_MESSAGE, Answerer
from uaw.main import create_app
from uaw.retrieval.retriever import Retriever
from uaw.services import Services

pytestmark = [pytest.mark.db, pytest.mark.anyio]


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
    app = create_app(Settings(_env_file=None, app_env="test"))
    app.dependency_overrides[get_services] = lambda: services
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")


@pytest.fixture
def model() -> FakeAnswerModel:
    # S1 and S2 are retrieved (top_k=2); S3 is invented by the model.
    return FakeAnswerModel("Tokens are checked in auth [S1], see also [S3].")


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession], model: FakeAnswerModel
) -> AsyncIterator[httpx.AsyncClient]:
    async with client_for(session_factory, model) as http:
        yield http


async def test_answer_cites_retrieved_lines_only(
    client: httpx.AsyncClient,
    model: FakeAnswerModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            files={
                "src/auth.py": [vector((0, 1.0))],
                "src/util.py": [vector((0, 1.0), (1, 1.0))],
                "src/far.py": [vector((1, 1.0))],  # not in the top 2
            },
        )

    response = await client.post(
        "/ask", json={"repository": "octo/demo", "question": "Where are tokens checked?"}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "Tokens are checked in auth [S1], see also."
    assert body["insufficient_context"] is False
    assert body["model"] == "fake-model"
    assert body["commit_sha"] == SHA_NEW
    assert body["citations"] == [
        {
            "id": "S1",
            "path": "src/auth.py",
            "start_line": 1,
            "end_line": 1,
            "url": f"https://github.com/octo/demo/blob/{SHA_NEW}/src/auth.py#L1",
        }
    ]
    # The model saw the two retrieved passages, not the third file.
    _, user_message = model.calls[0]
    assert '<source id="S1" path="src/auth.py"' in user_message
    assert '<source id="S2" path="src/util.py"' in user_message
    assert "src/far.py" not in user_message
    assert "Where are tokens checked?" in user_message


async def test_empty_repository_is_answered_without_calling_the_model(
    client: httpx.AsyncClient,
    model: FakeAnswerModel,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={})

    response = await client.post("/ask", json={"repository": "octo/demo", "question": "Why?"})

    assert response.status_code == 200
    assert response.json()["answer"] == NO_SOURCES_MESSAGE
    assert response.json()["insufficient_context"] is True
    assert model.calls == []


async def test_unknown_repository_is_404(client: httpx.AsyncClient, model: FakeAnswerModel) -> None:
    response = await client.post("/ask", json={"repository": "octo/none", "question": "Why?"})

    assert response.status_code == 404
    assert model.calls == []


async def test_answer_explains_its_evidence(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            files={
                "src/auth.py": [vector((0, 1.0))],
                "src/util.py": [vector((0, 1.0), (1, 1.0))],
                "src/far.py": [vector((1, 1.0))],  # not in the top 2
            },
        )

    response = await client.post(
        "/ask", json={"repository": "octo/demo", "question": "Where are tokens checked?"}
    )

    trace = response.json()["trace"]
    # Every passage shown to the model, best first, and whether the answer uses it.
    assert [(p["id"], p["path"], p["cited"]) for p in trace["passages"]] == [
        ("S1", "src/auth.py", True),
        ("S2", "src/util.py", False),
    ]
    assert trace["passages"][0]["content"] == "line 0\n"
    assert trace["passages"][0]["score"] > trace["passages"][1]["score"]
    # The model cited S3, which it was never given: removed, and reported.
    assert trace["removed_citations"] == ["S3"]
    assert (trace["input_tokens"], trace["output_tokens"]) == (100, 20)
    assert trace["retrieval_ms"] >= 0
    assert trace["generation_ms"] >= 0

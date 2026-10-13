"""Vector search against PostgreSQL + pgvector, with hand-made vectors."""

import random
import uuid
from collections.abc import AsyncIterator, Sequence

import httpx2 as httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.api.deps import get_services
from uaw.config import Settings
from uaw.connectors.github.client import RepositoryInfo
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument
from uaw.main import create_app
from uaw.retrieval.retriever import (
    EmbeddingModelMismatchError,
    RepositoryNotIndexedError,
    Retriever,
)
from uaw.services import Services
from uaw.storage.models import EMBEDDING_DIMENSIONS
from uaw.storage.search import ChunkSearch
from uaw.storage.store import SnapshotStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

MODEL = "fake-embedder"
SHA_OLD = "a" * 40
SHA_NEW = "b" * 40
DEMO = GitHubRepoRef(owner="octo", name="demo")


def vector(*weights: tuple[int, float]) -> list[float]:
    """A vector with the given (axis, value) components and zeros elsewhere."""
    values = [0.0] * EMBEDDING_DIMENSIONS
    for axis, value in weights:
        values[axis] = value
    return values


QUERY = vector((0, 1.0))


def noisy(base: list[float], scale: float, rng: random.Random) -> list[float]:
    return [value + rng.gauss(0, scale) for value in base]


class AxisEmbedder:
    """Every query is embedded as QUERY, so that the expected ranking is known."""

    def __init__(self, model: str = MODEL) -> None:
        self._model = model
        self.queries: list[str] = []

    @property
    def model(self) -> str:
        return self._model

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        raise AssertionError("not used by search")

    async def embed_query(self, text: str) -> list[float]:
        self.queries.append(text)
        return QUERY


async def add_snapshot(
    session: AsyncSession,
    *,
    repository: GitHubRepoRef = DEMO,
    sha: str = SHA_NEW,
    model: str = MODEL,
    files: dict[str, list[list[float]]],
    ready: bool = True,
) -> uuid.UUID:
    """Save one snapshot whose files have one single-line chunk per given vector."""
    store = SnapshotStore(session)
    repository_id = await store.upsert_repository(
        RepositoryInfo(
            ref=repository, default_branch="main", size_kb=1, private=False, description=None
        )
    )
    snapshot_id = await store.create_snapshot(repository_id, sha, embedding_model=model)
    for path, vectors in files.items():
        lines = [f"line {i}\n" for i in range(len(vectors))]
        document = SourceDocument(path=path, language="python", content="".join(lines))
        chunks = [
            Chunk(path=path, language="python", start_line=i + 1, end_line=i + 1, content=line)
            for i, line in enumerate(lines)
        ]
        chunk_ids = await store.add_document(snapshot_id, document, chunks)
        await store.set_embeddings(dict(zip(chunk_ids, vectors, strict=True)))
    if ready:
        await store.mark_snapshot_ready(snapshot_id)
    return snapshot_id


async def test_hits_are_ranked_by_cosine_similarity_with_permalinks(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session,
            files={
                "src/far.py": [vector((1, 1.0))],  # orthogonal to the query
                "src/near.py": [vector((0, 1.0), (1, 0.1)), vector((0, 1.0), (1, 1.0))],
            },
        )
    embedder = AxisEmbedder()

    result = await Retriever(session_factory, embedder).search(DEMO, "Where?", top_k=10)

    assert embedder.queries == ["Where?"]
    assert result.repository == "octo/demo"
    assert result.commit_sha == SHA_NEW
    assert [(hit.path, hit.start_line) for hit in result.hits] == [
        ("src/near.py", 1),
        ("src/near.py", 2),
        ("src/far.py", 1),
    ]
    scores = [hit.score for hit in result.hits]
    assert scores == sorted(scores, reverse=True)
    assert scores[0] == pytest.approx(1 / (1 + 0.1**2) ** 0.5)
    assert scores[-1] == pytest.approx(0.0, abs=1e-6)
    assert result.hits[0].url == f"https://github.com/octo/demo/blob/{SHA_NEW}/src/near.py#L1"
    assert result.hits[0].content == "line 0\n"


async def test_top_k_limits_the_number_of_hits(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(
            session, files={"a.py": [vector((0, 1.0), (i, 0.5)) for i in range(1, 8)]}
        )

    result = await Retriever(session_factory, AxisEmbedder()).search(DEMO, "q", top_k=3)

    assert len(result.hits) == 3


async def test_search_uses_the_latest_ready_snapshot_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, sha=SHA_OLD, files={"old.py": [QUERY]})
        await add_snapshot(session, sha=SHA_NEW, files={"new.py": [QUERY]})
        # Another repository with a perfect match must never leak into the results.
        await add_snapshot(
            session, repository=GitHubRepoRef(owner="other", name="repo"), files={"x.py": [QUERY]}
        )

    result = await Retriever(session_factory, AxisEmbedder()).search(
        GitHubRepoRef(owner="Octo", name="DEMO"), "q", top_k=10
    )

    assert result.commit_sha == SHA_NEW
    assert [hit.path for hit in result.hits] == ["new.py"]


async def test_snapshot_still_indexing_is_not_searchable(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={"a.py": [QUERY]}, ready=False)
    embedder = AxisEmbedder()

    with pytest.raises(RepositoryNotIndexedError):
        await Retriever(session_factory, embedder).search(DEMO, "q", top_k=5)
    assert embedder.queries == []  # no API call for an impossible search


async def test_snapshot_embedded_with_another_model_is_refused(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, model="old-model", files={"a.py": [QUERY]})

    with pytest.raises(EmbeddingModelMismatchError):
        await Retriever(session_factory, AxisEmbedder()).search(DEMO, "q", top_k=5)


async def test_filtered_hnsw_search_still_returns_enough_rows(session: AsyncSession) -> None:
    """Regression test for filtered approximate search.

    Another repository holds 300 chunks closer to the query than any chunk of the
    searched snapshot. The HNSW index alone would return the nearest candidates of
    the whole table (all from the other repository), then filter them all out.
    Random vectors are used: hand-made ones at equal distances from each other
    produce a degenerate HNSW graph.
    """
    rng = random.Random(42)
    await add_snapshot(
        session,
        repository=GitHubRepoRef(owner="noisy", name="neighbour"),
        files={"decoy.py": [noisy(QUERY, 0.02, rng) for _ in range(300)]},
    )
    target = await add_snapshot(
        session, files={"target.py": [noisy(vector(), 0.05, rng) for _ in range(5)]}
    )
    # Force the plan that exposes the problem: the vector index, without the
    # snapshot_id index (dropped inside this transaction, rolled back afterwards).
    await session.execute(text("DROP INDEX ix_chunks_snapshot_id"))
    await session.execute(text("SET LOCAL enable_seqscan = off"))
    query_literal = "[" + ",".join(map(str, QUERY)) + "]"
    raw_search = (
        f"SELECT id FROM chunks WHERE snapshot_id = '{target}' "
        f"ORDER BY embedding <=> '{query_literal}' LIMIT 5"
    )

    plan = "\n".join((await session.scalars(text(f"EXPLAIN {raw_search}"))).all())
    assert "ix_chunks_embedding_hnsw" in plan
    # Without iterative scans, the filtered index search loses the target chunks.
    assert len((await session.execute(text(raw_search))).all()) < 5

    matches = await ChunkSearch(session).nearest_chunks(target, QUERY, limit=5)

    assert [m.path for m in matches] == ["target.py"] * 5


@pytest.fixture
async def client(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(Settings(_env_file=None, app_env="test"))
    services = Services(
        session_factory=session_factory,
        runner=None,
        retriever=Retriever(session_factory, AxisEmbedder()),
    )
    app.dependency_overrides[get_services] = lambda: services
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
        yield http


async def test_search_endpoint_returns_ranked_hits(
    client: httpx.AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    async with session_factory.begin() as session:
        await add_snapshot(session, files={"src/auth.py": [QUERY]})

    response = await client.post(
        "/search", json={"repository": "Octo/Demo", "query": "  Where is auth?  ", "top_k": 5}
    )

    assert response.status_code == 200
    body = response.json()
    assert body["repository"] == "octo/demo"
    assert body["hits"][0]["path"] == "src/auth.py"
    assert body["hits"][0]["score"] == pytest.approx(1.0)


async def test_search_endpoint_unknown_repository_is_404(client: httpx.AsyncClient) -> None:
    response = await client.post("/search", json={"repository": "octo/nothing", "query": "q"})

    assert response.status_code == 404
    assert "octo/nothing" in response.json()["detail"]

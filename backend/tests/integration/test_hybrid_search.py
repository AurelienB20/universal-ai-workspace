"""Full-text and hybrid search against PostgreSQL, with hand-made content and vectors."""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_search import DEMO, MODEL, QUERY, SHA_NEW, AxisEmbedder, vector
from uaw.connectors.github.client import RepositoryInfo
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument
from uaw.retrieval.retriever import RetrievalOptions, Retriever
from uaw.storage.fulltext import text_matches
from uaw.storage.models import ChunkRow
from uaw.storage.store import SnapshotStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

QUESTION = "What does after_this_request do?"


async def add_files(
    session_factory: async_sessionmaker[AsyncSession],
    files: dict[str, tuple[str, list[float]]],
    repository: GitHubRepoRef = DEMO,
) -> uuid.UUID:
    """One single-chunk document per file: path -> (content, vector)."""
    async with session_factory.begin() as session:
        store = SnapshotStore(session)
        repository_id = await store.upsert_repository(
            RepositoryInfo(
                ref=repository, default_branch="main", size_kb=1, private=False, description=None
            )
        )
        snapshot_id = await store.create_snapshot(repository_id, SHA_NEW, embedding_model=MODEL)
        for path, (content, embedding) in files.items():
            document = SourceDocument(path=path, language="python", content=content)
            chunk = Chunk(path=path, language="python", start_line=1, end_line=1, content=content)
            [chunk_id] = await store.add_document(snapshot_id, document, [chunk])
            await store.set_embeddings({chunk_id: embedding})
        await store.mark_snapshot_ready(snapshot_id)
    return snapshot_id


FILES = {
    # Close to the question in vector space, but about something else.
    "src/near.py": ("def unrelated_helper(): return 1", vector((0, 1.0))),
    # The definition: far in vector space, but it holds the exact name.
    "src/ctx.py": ("def after_this_request(f): register f", vector((0, 0.2), (1, 1.0))),
    "docs/other.rst": ("Nothing to see here.", vector((0, 0.5), (2, 1.0))),
}


async def test_ready_snapshots_get_their_full_text_vectors(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory, FILES)

    async with session_factory() as session:
        missing = await session.scalar(
            select(func.count()).select_from(ChunkRow).where(ChunkRow.search_vector.is_(None))
        )
    assert missing == 0


async def test_full_text_finds_an_exact_name(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    snapshot_id = await add_files(session_factory, FILES)
    # The same name in another repository must never leak into the results.
    await add_files(
        session_factory,
        {"x.py": ("def after_this_request(): pass", QUERY)},
        repository=GitHubRepoRef(owner="other", name="repo"),
    )

    async with session_factory() as session:
        ids = await text_matches(session, snapshot_id, QUESTION, limit=10)
        contents = [
            await session.scalar(select(ChunkRow.content).where(ChunkRow.id == chunk_id))
            for chunk_id in ids
        ]

    assert contents == ["def after_this_request(f): register f"]


async def test_hybrid_search_ranks_the_exact_name_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory, FILES)

    plain = await Retriever(session_factory, AxisEmbedder()).search(DEMO, QUESTION, top_k=3)
    hybrid = await Retriever(
        session_factory, AxisEmbedder(), RetrievalOptions(mode="hybrid")
    ).search(DEMO, QUESTION, top_k=3)

    assert plain.hits[0].path == "src/near.py"
    assert hybrid.hits[0].path == "src/ctx.py"
    # Scores stay cosine similarities, whatever the ranking.
    by_path = {hit.path: hit.score for hit in hybrid.hits}
    assert by_path["src/near.py"] == pytest.approx(1.0)
    assert by_path["src/ctx.py"] == pytest.approx(0.2 / (0.2**2 + 1) ** 0.5)


async def test_chunks_found_by_text_only_are_returned_with_their_similarity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory, FILES)
    # One vector candidate only: src/ctx.py comes from the full-text ranking alone.
    options = RetrievalOptions(mode="hybrid", candidates=1)

    result = await Retriever(session_factory, AxisEmbedder(), options).search(
        DEMO, QUESTION, top_k=2
    )

    assert {hit.path for hit in result.hits} == {"src/near.py", "src/ctx.py"}
    ctx = next(hit for hit in result.hits if hit.path == "src/ctx.py")
    assert ctx.score == pytest.approx(0.2 / (0.2**2 + 1) ** 0.5)


async def test_test_files_can_rank_below_source_files(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(
        session_factory,
        {
            "tests/test_app.py": ("def test_app(): assert app", vector((0, 1.0))),
            "src/app.py": ("def app(): pass", vector((0, 1.0), (1, 0.3))),
        },
    )

    plain = await Retriever(session_factory, AxisEmbedder()).search(DEMO, "app", top_k=2)
    demoted = await Retriever(
        session_factory, AxisEmbedder(), RetrievalOptions(test_weight=0.5)
    ).search(DEMO, "app", top_k=2)

    assert [hit.path for hit in plain.hits] == ["tests/test_app.py", "src/app.py"]
    assert [hit.path for hit in demoted.hits] == ["src/app.py", "tests/test_app.py"]


async def test_a_question_about_tests_keeps_test_files_first(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(
        session_factory,
        {
            "tests/test_app.py": ("def test_app(): assert app", vector((0, 1.0))),
            "src/app.py": ("def app(): pass", vector((0, 1.0), (1, 0.3))),
        },
    )
    options = RetrievalOptions(test_weight=0.5)

    result = await Retriever(session_factory, AxisEmbedder(), options).search(
        DEMO, "Where are the tests of app?", top_k=2
    )

    assert [hit.path for hit in result.hits] == ["tests/test_app.py", "src/app.py"]

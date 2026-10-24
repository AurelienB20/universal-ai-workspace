"""Reranking inside the real search, with a fake reranker."""

from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_hybrid_search import FILES, add_files
from tests.integration.test_search import DEMO, AxisEmbedder, vector
from uaw.retrieval.retriever import RetrievalOptions, Retriever

pytestmark = [pytest.mark.db, pytest.mark.anyio]


class KeywordReranker:
    """Scores a document by whether it contains a keyword; records what it was given."""

    def __init__(self, keyword: str) -> None:
        self.keyword = keyword
        self.calls: list[tuple[str, list[str]]] = []

    @property
    def model(self) -> str:
        return "fake-rerank"

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        self.calls.append((query, list(documents)))
        return [0.9 if self.keyword in document else 0.1 for document in documents]


async def test_the_reranker_reorders_the_candidates(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory, FILES)
    reranker = KeywordReranker("after_this_request")
    retriever = Retriever(session_factory, AxisEmbedder(), reranker=reranker)

    result = await retriever.search(DEMO, "What does it do?", top_k=2)

    # Vector search alone puts src/near.py first; the reranker prefers src/ctx.py. The
    # two others tie at 0.1: their order is not checked.
    assert result.hits[0].path == "src/ctx.py"
    assert [hit.rerank_score for hit in result.hits] == [0.9, 0.1]
    # The displayed similarity stays the cosine score.
    assert result.hits[0].score == pytest.approx(0.2 / (0.2**2 + 1) ** 0.5)
    # Every candidate was read with its path, as for its embedding.
    [(query, documents)] = reranker.calls
    assert query == "What does it do?"
    assert len(documents) == 3
    assert documents[0].startswith("File: src/near.py\n")


async def test_only_rerank_candidates_are_sent(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(session_factory, FILES)
    reranker = KeywordReranker("x")
    options = RetrievalOptions(rerank_candidates=2)

    await Retriever(session_factory, AxisEmbedder(), options, reranker).search(DEMO, "q", top_k=1)

    assert len(reranker.calls[0][1]) == 2


async def test_test_files_rank_lower_after_reranking(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await add_files(
        session_factory,
        {
            "tests/test_app.py": ("def test_app(): app", vector((0, 1.0))),
            "src/app.py": ("def app(): pass", vector((0, 1.0), (1, 0.3))),
        },
    )
    reranker = KeywordReranker("app")  # both score 0.9
    options = RetrievalOptions(test_weight=0.5)
    retriever = Retriever(session_factory, AxisEmbedder(), options, reranker)

    plain = await retriever.search(DEMO, "What is app?", top_k=2)
    about_tests = await retriever.search(DEMO, "Where are the tests of app?", top_k=2)

    assert [hit.path for hit in plain.hits] == ["src/app.py", "tests/test_app.py"]
    # Equal scores, no down-weighting: the chunk id decides, so only check both are there.
    assert {hit.path for hit in about_tests.hits} == {"src/app.py", "tests/test_app.py"}
    assert about_tests.hits[0].rerank_score == about_tests.hits[1].rerank_score == 0.9

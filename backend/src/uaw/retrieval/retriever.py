"""Search over an imported repository (no LLM involved).

Given a question, returns the chunks of the repository's latest searchable snapshot that
best match it, each with a permanent link to its lines. Two modes:

- **vector**: the chunks closest to the question in embedding space;
- **hybrid**: the vector ranking and a full-text ranking (storage/fulltext.py), merged
  with Reciprocal Rank Fusion. RRF combines ranks, not scores: a cosine similarity and a
  text rank are not on comparable scales, and ranks need no calibration.

Either mode can rank test files lower (``test_weight``): tests repeat names, so they look
close to a question about a name. Each option is kept only if the evaluation shows it helps.
"""

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.connectors.github.links import line_permalink
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.chunks import Chunk
from uaw.embeddings.base import Embedder, embedding_text
from uaw.storage.fulltext import text_matches
from uaw.storage.search import HNSW_EF_SEARCH, ChunkMatch, ChunkSearch, SearchableSnapshot

RetrievalMode = Literal["vector", "hybrid"]
TextTerms = Literal["names", "words"]

# A question about tests: test files must not be ranked lower for it.
_MENTIONS_TESTS = re.compile(r"\btests?\b", re.IGNORECASE)


@dataclass(frozen=True)
class RetrievalOptions:
    mode: RetrievalMode = "vector"
    # Weight of the full-text ranking in the fusion (the vector ranking weighs 1).
    text_weight: float = 1.0
    # What the full-text search looks for: the code names of the question, or every word.
    text_terms: TextTerms = "names"
    # Multiplies the fused score of chunks from test files: below 1 ranks them lower,
    # except for questions that mention tests.
    test_weight: float = 1.0
    # Chunks taken from each ranking before fusing them.
    candidates: int = 50
    # The usual RRF constant: it flattens the gap between the very first ranks.
    rrf_k: int = 60
    # Chunks given to the reranker, when one is configured.
    rerank_candidates: int = 30

    def __post_init__(self) -> None:
        if not 1 <= self.candidates <= HNSW_EF_SEARCH:
            raise ValueError(f"candidates must be between 1 and {HNSW_EF_SEARCH}")
        if not 1 <= self.rerank_candidates <= HNSW_EF_SEARCH:
            raise ValueError(f"rerank_candidates must be between 1 and {HNSW_EF_SEARCH}")
        if self.text_weight < 0 or not 0 < self.test_weight <= 1:
            raise ValueError("text_weight must be >= 0 and test_weight in (0, 1]")

    @property
    def reorders(self) -> bool:
        """Whether results can differ from the plain vector ranking."""
        return self.mode == "hybrid" or self.test_weight != 1.0


def is_test_path(path: str) -> bool:
    """Whether a file holds tests: a tests/ directory, or test_*.py / *_test.py."""
    *directories, name = path.split("/")
    return (
        any(part in ("test", "tests") for part in directories)
        or name.startswith("test_")
        or name.endswith(("_test.py", "_tests.py"))
    )


def fuse(
    rankings: Sequence[tuple[Sequence[uuid.UUID], float]], *, k: int
) -> dict[uuid.UUID, float]:
    """Reciprocal Rank Fusion: each ranking adds weight / (k + rank) to its items."""
    scores: dict[uuid.UUID, float] = {}
    for ranking, weight in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + weight / (k + rank)
    return scores


def ranked(
    scores: dict[uuid.UUID, float],
    paths: Callable[[uuid.UUID], str],
    *,
    test_weight: float,
    limit: int,
) -> list[uuid.UUID]:
    """The ``limit`` best items, test files down-weighted; ties broken by id."""
    adjusted = {
        item: score * (test_weight if is_test_path(paths(item)) else 1.0)
        for item, score in scores.items()
    }
    return sorted(adjusted, key=lambda item: (-adjusted[item], str(item)))[:limit]


class RetrievalError(Exception):
    """Base class for search errors. Messages are user-facing."""


class RepositoryNotIndexedError(RetrievalError):
    """The repository has no searchable snapshot (never imported, or still indexing)."""

    @classmethod
    def for_repository(cls, repository: GitHubRepoRef) -> "RepositoryNotIndexedError":
        return cls(
            f"{repository.full_name} has not been imported yet, or its import is not finished."
        )


class EmbeddingModelMismatchError(RetrievalError):
    """The snapshot was embedded with another model than the one configured now."""


class SearchHit(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    path: str
    language: str
    start_line: int
    end_line: int
    section: str | None
    content: str
    # Cosine similarity between the question and the chunk: higher is closer.
    # Useful to compare hits of one search, not as an absolute relevance threshold.
    score: float
    # Relevance given by the reranker, when one reordered the results (None otherwise).
    rerank_score: float | None = None
    # Permanent link to the exact lines, at the snapshot's commit.
    url: str


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    commit_sha: str
    snapshot_id: uuid.UUID
    hits: list[SearchHit]


class Reranker(Protocol):
    """Scores documents against a query by reading both together."""

    @property
    def model(self) -> str: ...

    async def rerank(self, query: str, documents: Sequence[str]) -> list[float]:
        """One relevance score per document, in input order."""
        ...


class Retriever:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        embedder: Embedder,
        options: RetrievalOptions | None = None,
        reranker: Reranker | None = None,
    ) -> None:
        self._sessions = session_factory
        self._embedder = embedder
        self._options = options or RetrievalOptions()
        self._reranker = reranker

    @property
    def options(self) -> RetrievalOptions:
        return self._options

    @property
    def rerank_model(self) -> str | None:
        return None if self._reranker is None else self._reranker.model

    async def find_snapshot(self, repository: GitHubRepoRef) -> SearchableSnapshot:
        """The snapshot a search would use. Raises if it cannot be searched."""
        async with self._sessions() as session:
            snapshot = await ChunkSearch(session).latest_ready_snapshot(repository.full_name)
        if snapshot is None:
            raise RepositoryNotIndexedError.for_repository(repository)
        # Vectors from two different models live in unrelated spaces: comparing them
        # would silently return meaningless results.
        if snapshot.embedding_model != self._embedder.model:
            raise EmbeddingModelMismatchError(
                f"{snapshot.repository} was indexed with another embedding model. "
                "Import it again to search it."
            )
        return snapshot

    async def search(self, repository: GitHubRepoRef, query: str, *, top_k: int) -> SearchResult:
        # The snapshot is checked first, so that an impossible search costs no API call.
        snapshot = await self.find_snapshot(repository)
        # No database connection is held during the embedding and reranking API calls.
        query_vector = await self._embedder.embed_query(query)
        limit = top_k if self._reranker is None else max(self._options.rerank_candidates, top_k)
        async with self._sessions() as session:
            matches = await self._matches(session, snapshot.id, query, query_vector, limit)
        rerank_scores: list[float | None] = [None] * len(matches)
        if self._reranker is not None and matches:
            matches, rerank_scores = await self._rerank(query, matches, top_k)

        hits = [
            SearchHit(
                chunk_id=match.chunk_id,
                path=match.path,
                language=match.language,
                start_line=match.start_line,
                end_line=match.end_line,
                section=match.section,
                content=match.content,
                score=1.0 - match.distance,
                rerank_score=rerank_score,
                url=line_permalink(
                    snapshot.repository,
                    snapshot.commit_sha,
                    match.path,
                    match.start_line,
                    match.end_line,
                ),
            )
            for match, rerank_score in zip(matches, rerank_scores, strict=True)
        ]
        return SearchResult(
            repository=snapshot.repository,
            commit_sha=snapshot.commit_sha,
            snapshot_id=snapshot.id,
            hits=hits,
        )

    async def _matches(
        self,
        session: AsyncSession,
        snapshot_id: uuid.UUID,
        query: str,
        query_vector: Sequence[float],
        top_k: int,
    ) -> list[ChunkMatch]:
        options = self._options
        search = ChunkSearch(session)
        if not options.reorders:
            return await search.nearest_chunks(snapshot_id, query_vector, limit=top_k)

        test_weight = self._test_weight(query)
        if options.mode == "vector" and test_weight == 1.0:
            return await search.nearest_chunks(snapshot_id, query_vector, limit=top_k)

        candidates = max(options.candidates, top_k)
        nearest = await search.nearest_chunks(snapshot_id, query_vector, limit=candidates)
        rankings: list[tuple[Sequence[uuid.UUID], float]] = [
            ([match.chunk_id for match in nearest], 1.0)
        ]
        by_id = {match.chunk_id: match for match in nearest}
        if options.mode == "hybrid":
            text_ids = await text_matches(
                session,
                snapshot_id,
                query,
                limit=candidates,
                names_only=options.text_terms == "names",
            )
            rankings.append((text_ids, options.text_weight))
            # Chunks found by text only still get their real similarity to the question.
            missing = [chunk_id for chunk_id in text_ids if chunk_id not in by_id]
            by_id |= await search.chunks_by_id(snapshot_id, missing, query_vector)

        best = ranked(
            fuse(rankings, k=options.rrf_k),
            lambda chunk_id: by_id[chunk_id].path,
            test_weight=test_weight,
            limit=top_k,
        )
        return [by_id[chunk_id] for chunk_id in best]

    def _test_weight(self, query: str) -> float:
        return 1.0 if _MENTIONS_TESTS.search(query) else self._options.test_weight

    async def _rerank(
        self, query: str, matches: list[ChunkMatch], top_k: int
    ) -> tuple[list[ChunkMatch], list[float | None]]:
        """Reorder the candidates by the reranker's relevance (test files down-weighted
        the same way), and keep the ``top_k`` best."""
        assert self._reranker is not None
        documents = [rerank_text(match) for match in matches]
        scores = await self._reranker.rerank(query, documents)
        test_weight = self._test_weight(query)

        def key(index: int) -> tuple[float, str]:
            weight = test_weight if is_test_path(matches[index].path) else 1.0
            return (-scores[index] * weight, str(matches[index].chunk_id))

        order = sorted(range(len(matches)), key=key)[:top_k]
        return [matches[i] for i in order], [scores[i] for i in order]


def rerank_text(match: ChunkMatch) -> str:
    """The text the reranker reads for a chunk: the same as for its embedding."""
    return embedding_text(
        Chunk(
            path=match.path,
            language=match.language,
            start_line=match.start_line,
            end_line=match.end_line,
            content=match.content,
            section=match.section,
        )
    )

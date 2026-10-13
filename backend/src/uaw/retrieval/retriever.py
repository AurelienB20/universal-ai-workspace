"""Semantic search over an imported repository (no LLM involved).

Given a question, returns the chunks of the repository's latest searchable snapshot
that are closest to it in embedding space, each with a permanent link to its lines.
"""

import uuid

from pydantic import BaseModel, ConfigDict
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.connectors.github.links import line_permalink
from uaw.connectors.github.url import GitHubRepoRef
from uaw.embeddings.base import Embedder
from uaw.storage.search import ChunkSearch, SearchableSnapshot


class RetrievalError(Exception):
    """Base class for search errors. Messages are user-facing."""


class RepositoryNotIndexedError(RetrievalError):
    """The repository has no searchable snapshot (never imported, or still indexing)."""


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
    # Permanent link to the exact lines, at the snapshot's commit.
    url: str


class SearchResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    repository: str
    commit_sha: str
    snapshot_id: uuid.UUID
    hits: list[SearchHit]


class Retriever:
    def __init__(
        self, session_factory: async_sessionmaker[AsyncSession], embedder: Embedder
    ) -> None:
        self._sessions = session_factory
        self._embedder = embedder

    async def find_snapshot(self, repository: GitHubRepoRef) -> SearchableSnapshot:
        """The snapshot a search would use. Raises if it cannot be searched."""
        async with self._sessions() as session:
            snapshot = await ChunkSearch(session).latest_ready_snapshot(repository.full_name)
        if snapshot is None:
            raise RepositoryNotIndexedError(
                f"{repository.full_name} has not been imported yet, or its import is not finished."
            )
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
        # No database connection is held during the embedding API call.
        query_vector = await self._embedder.embed_query(query)
        async with self._sessions() as session:
            matches = await ChunkSearch(session).nearest_chunks(
                snapshot.id, query_vector, limit=top_k
            )

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
                url=line_permalink(
                    snapshot.repository,
                    snapshot.commit_sha,
                    match.path,
                    match.start_line,
                    match.end_line,
                ),
            )
            for match in matches
        ]
        return SearchResult(
            repository=snapshot.repository,
            commit_sha=snapshot.commit_sha,
            snapshot_id=snapshot.id,
            hits=hits,
        )

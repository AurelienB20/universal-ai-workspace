"""Vector search over the chunks of one snapshot (pgvector, cosine distance)."""

import uuid
from collections.abc import Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.storage.models import (
    EMBEDDING_DIMENSIONS,
    ChunkRow,
    DocumentRow,
    RepositoryRow,
    SnapshotRow,
)
from uaw.storage.store import SnapshotStatus

# Candidates the HNSW index keeps per search step. Must be at least the largest
# requested ``limit``, otherwise pgvector returns fewer rows than asked.
HNSW_EF_SEARCH = 100


class SearchableSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    # Canonical "Owner/Name", as reported by GitHub (used to build links).
    repository: str
    commit_sha: str
    embedding_model: str


class ChunkMatch(BaseModel):
    model_config = ConfigDict(frozen=True)

    chunk_id: uuid.UUID
    path: str
    language: str
    start_line: int
    end_line: int
    section: str | None
    content: str
    # Cosine distance: 0 = same direction, 2 = opposite.
    distance: float


class ChunkSearch:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def latest_ready_snapshot(self, repository_key: str) -> SearchableSnapshot | None:
        """The most recent searchable snapshot of a repository ("owner/name", any case)."""
        stmt = (
            select(
                SnapshotRow.id,
                RepositoryRow.owner,
                RepositoryRow.name,
                SnapshotRow.commit_sha,
                SnapshotRow.embedding_model,
            )
            .join(RepositoryRow, SnapshotRow.repository_id == RepositoryRow.id)
            .where(
                RepositoryRow.key == repository_key.lower(),
                SnapshotRow.status == SnapshotStatus.READY,
            )
            .order_by(SnapshotRow.created_at.desc(), SnapshotRow.id)
            .limit(1)
        )
        row = (await self._session.execute(stmt)).one_or_none()
        if row is None:
            return None
        return SearchableSnapshot(
            id=row.id,
            repository=f"{row.owner}/{row.name}",
            commit_sha=row.commit_sha,
            embedding_model=row.embedding_model,
        )

    async def nearest_chunks(
        self, snapshot_id: uuid.UUID, query_vector: Sequence[float], *, limit: int
    ) -> list[ChunkMatch]:
        """The ``limit`` chunks of the snapshot closest to the query, closest first."""
        if len(query_vector) != EMBEDDING_DIMENSIONS:
            raise ValueError(
                f"Query vector has {len(query_vector)} dimensions, expected {EMBEDDING_DIMENSIONS}"
            )
        if not 1 <= limit <= HNSW_EF_SEARCH:
            raise ValueError(f"limit must be between 1 and {HNSW_EF_SEARCH}")

        # The HNSW index covers every snapshot. Without iterative scans, it returns the
        # nearest chunks of the whole table and only then applies the snapshot filter,
        # which can leave fewer than ``limit`` rows (or none). With them, pgvector keeps
        # scanning the index until enough rows pass the filter. "strict_order" keeps
        # results exactly sorted by distance. SET LOCAL lasts until the transaction ends.
        await self._session.execute(text("SET LOCAL hnsw.iterative_scan = strict_order"))
        await self._session.execute(text(f"SET LOCAL hnsw.ef_search = {HNSW_EF_SEARCH}"))

        distance = ChunkRow.embedding.cosine_distance(list(query_vector)).label("distance")
        # The nearest-neighbour query reads the chunks table only, so that the planner
        # can use the vector index; file paths are joined on the few selected rows.
        nearest = (
            select(ChunkRow.id, distance)
            .where(ChunkRow.snapshot_id == snapshot_id)
            .order_by(distance)
            .limit(limit)
            .subquery()
        )
        stmt = (
            select(ChunkRow, DocumentRow.path, DocumentRow.language, nearest.c.distance)
            .join(nearest, ChunkRow.id == nearest.c.id)
            .join(DocumentRow, ChunkRow.document_id == DocumentRow.id)
            # The chunk id breaks ties, so that the order is deterministic.
            .order_by(nearest.c.distance, ChunkRow.id)
        )
        return [
            ChunkMatch(
                chunk_id=row.id,
                path=path,
                language=language,
                start_line=row.start_line,
                end_line=row.end_line,
                section=row.section,
                content=row.content,
                distance=dist,
            )
            for row, path, language, dist in (await self._session.execute(stmt)).all()
        ]

    async def chunks_by_id(
        self, snapshot_id: uuid.UUID, ids: Sequence[uuid.UUID], query_vector: Sequence[float]
    ) -> dict[uuid.UUID, ChunkMatch]:
        """The given chunks of the snapshot, with their distance to the query (for chunks
        found by full-text search, whose similarity is still shown to users)."""
        if not ids:
            return {}
        distance = ChunkRow.embedding.cosine_distance(list(query_vector)).label("distance")
        stmt = (
            select(ChunkRow, DocumentRow.path, DocumentRow.language, distance)
            .join(DocumentRow, ChunkRow.document_id == DocumentRow.id)
            .where(ChunkRow.snapshot_id == snapshot_id, ChunkRow.id.in_(ids))
        )
        return {
            row.id: ChunkMatch(
                chunk_id=row.id,
                path=path,
                language=language,
                start_line=row.start_line,
                end_line=row.end_line,
                section=row.section,
                content=row.content,
                distance=dist,
            )
            for row, path, language, dist in (await self._session.execute(stmt)).all()
        }

    async def document_paths(self, snapshot_id: uuid.UUID) -> set[str]:
        stmt = select(DocumentRow.path).where(DocumentRow.snapshot_id == snapshot_id)
        return set((await self._session.scalars(stmt)).all())

    async def document_line_counts(self, snapshot_id: uuid.UUID) -> dict[str, int]:
        """Last line covered by a chunk, per indexed file of the snapshot (0 if the file
        has no chunk, e.g. an empty file)."""
        stmt = (
            select(DocumentRow.path, func.coalesce(func.max(ChunkRow.end_line), 0))
            .outerjoin(ChunkRow, ChunkRow.document_id == DocumentRow.id)
            .where(DocumentRow.snapshot_id == snapshot_id)
            .group_by(DocumentRow.path)
        )
        return {path: int(lines) for path, lines in (await self._session.execute(stmt)).all()}

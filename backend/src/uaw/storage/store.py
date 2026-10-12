"""Persistence of imported repositories, their documents and chunks.

The store never commits: the caller owns the transaction, so that an import is
saved entirely or not at all (unit of work).
"""

import hashlib
import uuid
from collections.abc import Mapping, Sequence

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.connectors.github.client import RepositoryInfo
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument
from uaw.storage.models import (
    EMBEDDING_DIMENSIONS,
    ChunkRow,
    DocumentRow,
    RepositoryRow,
    SnapshotRow,
)


class SnapshotAlreadyExistsError(Exception):
    """This commit of the repository has already been imported."""


class StoredChunk(BaseModel):
    """A chunk together with its database identity."""

    model_config = ConfigDict(frozen=True)

    id: uuid.UUID
    document_id: uuid.UUID
    chunk: Chunk


class SnapshotStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_repository(self, info: RepositoryInfo) -> uuid.UUID:
        """Insert the repository, or refresh its metadata if it is already known."""
        insert_stmt = pg_insert(RepositoryRow).values(
            id=uuid.uuid4(),
            key=info.ref.full_name.lower(),
            owner=info.ref.owner,
            name=info.ref.name,
            default_branch=info.default_branch,
        )
        stmt = insert_stmt.on_conflict_do_update(
            index_elements=[RepositoryRow.key],
            set_={
                "owner": insert_stmt.excluded.owner,
                "name": insert_stmt.excluded.name,
                "default_branch": insert_stmt.excluded.default_branch,
            },
        ).returning(RepositoryRow.id)
        return (await self._session.execute(stmt)).scalar_one()

    async def find_snapshot(self, repository_id: uuid.UUID, commit_sha: str) -> uuid.UUID | None:
        stmt = select(SnapshotRow.id).where(
            SnapshotRow.repository_id == repository_id, SnapshotRow.commit_sha == commit_sha
        )
        return (await self._session.execute(stmt)).scalar_one_or_none()

    async def create_snapshot(self, repository_id: uuid.UUID, commit_sha: str) -> uuid.UUID:
        # ON CONFLICT DO NOTHING instead of catching IntegrityError: a failed statement
        # would abort the caller's whole transaction.
        stmt = (
            pg_insert(SnapshotRow)
            .values(id=uuid.uuid4(), repository_id=repository_id, commit_sha=commit_sha)
            .on_conflict_do_nothing(
                index_elements=[SnapshotRow.repository_id, SnapshotRow.commit_sha]
            )
            .returning(SnapshotRow.id)
        )
        snapshot_id = (await self._session.execute(stmt)).scalar_one_or_none()
        if snapshot_id is None:
            raise SnapshotAlreadyExistsError(f"Commit {commit_sha} is already imported.")
        return snapshot_id

    async def add_document(
        self, snapshot_id: uuid.UUID, document: SourceDocument, chunks: Sequence[Chunk]
    ) -> list[uuid.UUID]:
        """Save a document and its chunks. Returns the chunk IDs, in order."""
        if any(chunk.path != document.path for chunk in chunks):
            raise ValueError(f"All chunks must belong to {document.path}")

        document_id = uuid.uuid4()
        await self._session.execute(
            insert(DocumentRow).values(
                id=document_id,
                snapshot_id=snapshot_id,
                path=document.path,
                language=document.language,
                content_sha256=hashlib.sha256(document.content.encode()).hexdigest(),
            )
        )
        # IDs are generated here rather than by the database, so that a bulk insert
        # does not need RETURNING to know them.
        chunk_ids = [uuid.uuid4() for _ in chunks]
        if chunks:
            await self._session.execute(
                insert(ChunkRow),
                [
                    {
                        "id": chunk_id,
                        "document_id": document_id,
                        "snapshot_id": snapshot_id,
                        "ordinal": ordinal,
                        "start_line": chunk.start_line,
                        "end_line": chunk.end_line,
                        "section": chunk.section,
                        "content": chunk.content,
                    }
                    for ordinal, (chunk_id, chunk) in enumerate(zip(chunk_ids, chunks, strict=True))
                ],
            )
        return chunk_ids

    async def list_chunks(self, snapshot_id: uuid.UUID) -> list[StoredChunk]:
        """All chunks of a snapshot, ordered by file path then position in the file."""
        stmt = (
            select(ChunkRow, DocumentRow.path, DocumentRow.language)
            .join(DocumentRow, ChunkRow.document_id == DocumentRow.id)
            .where(ChunkRow.snapshot_id == snapshot_id)
            .order_by(DocumentRow.path, ChunkRow.ordinal)
        )
        return [
            StoredChunk(
                id=row.id,
                document_id=row.document_id,
                chunk=Chunk(
                    path=path,
                    language=language,
                    start_line=row.start_line,
                    end_line=row.end_line,
                    content=row.content,
                    section=row.section,
                ),
            )
            for row, path, language in (await self._session.execute(stmt)).all()
        ]

    async def set_embeddings(self, embeddings: Mapping[uuid.UUID, Sequence[float]]) -> None:
        for chunk_id, vector in embeddings.items():
            if len(vector) != EMBEDDING_DIMENSIONS:
                raise ValueError(
                    f"Embedding for chunk {chunk_id} has {len(vector)} dimensions, "
                    f"expected {EMBEDDING_DIMENSIONS}"
                )
        if embeddings:
            # Bulk UPDATE by primary key (one executemany round trip).
            await self._session.execute(
                update(ChunkRow),
                [{"id": chunk_id, "embedding": list(v)} for chunk_id, v in embeddings.items()],
            )

    async def delete_snapshot(self, snapshot_id: uuid.UUID) -> bool:
        """Delete a snapshot with its documents and chunks. Returns False if absent."""
        stmt = delete(SnapshotRow).where(SnapshotRow.id == snapshot_id).returning(SnapshotRow.id)
        return (await self._session.execute(stmt)).scalar_one_or_none() is not None

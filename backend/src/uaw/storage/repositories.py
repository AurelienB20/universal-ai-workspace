"""Read-only listing of the repositories that can be searched."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import distinct_on
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.storage.models import ChunkRow, DocumentRow, RepositoryRow, SnapshotRow
from uaw.storage.store import SnapshotStatus


class RepositorySummary(BaseModel):
    """A repository with its latest searchable snapshot (the one questions use)."""

    model_config = ConfigDict(frozen=True)

    # Canonical "Owner/Name", as reported by GitHub.
    repository: str
    default_branch: str
    commit_sha: str
    indexed_at: datetime
    documents_count: int
    chunks_count: int


class RepositoryCatalog:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_ready(self) -> list[RepositorySummary]:
        """Every repository that has a ready snapshot, sorted by name."""
        # Same choice as ChunkSearch.latest_ready_snapshot: the most recent ready one.
        latest = (
            select(
                SnapshotRow.id,
                SnapshotRow.repository_id,
                SnapshotRow.commit_sha,
                SnapshotRow.created_at,
            )
            .where(SnapshotRow.status == SnapshotStatus.READY)
            .order_by(SnapshotRow.repository_id, SnapshotRow.created_at.desc(), SnapshotRow.id)
            .ext(distinct_on(SnapshotRow.repository_id))
            .subquery()
        )
        documents = (
            select(func.count()).where(DocumentRow.snapshot_id == latest.c.id).scalar_subquery()
        )
        chunks = select(func.count()).where(ChunkRow.snapshot_id == latest.c.id).scalar_subquery()
        stmt = (
            select(
                RepositoryRow.owner,
                RepositoryRow.name,
                RepositoryRow.default_branch,
                latest.c.commit_sha,
                latest.c.created_at,
                documents.label("documents_count"),
                chunks.label("chunks_count"),
            )
            .join(latest, latest.c.repository_id == RepositoryRow.id)
            .order_by(RepositoryRow.key)
        )
        return [
            RepositorySummary(
                repository=f"{row.owner}/{row.name}",
                default_branch=row.default_branch,
                commit_sha=row.commit_sha,
                indexed_at=row.created_at,
                documents_count=row.documents_count,
                chunks_count=row.chunks_count,
            )
            for row in (await self._session.execute(stmt)).all()
        ]

"""Persistence of ingestion jobs. Like ``SnapshotStore``, it never commits."""

import uuid

from sqlalchemy import func, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.domain.jobs import ACTIVE_JOB_STATUSES, IngestionJob, JobStage, JobStatus
from uaw.storage.models import IngestionJobRow


class JobStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_or_get_active(self, repository: str) -> tuple[IngestionJob, bool]:
        """Queue an import of ``repository`` ("owner/name").

        Returns ``(job, created)``. If the repository already has a queued or running
        job, that job is returned instead and ``created`` is False.
        """
        key = repository.lower()
        # The partial unique index makes concurrent requests safe: only one INSERT
        # wins, the others fall back to reading the winner.
        for _ in range(3):
            stmt = (
                pg_insert(IngestionJobRow)
                .values(
                    id=uuid.uuid4(),
                    repository_key=key,
                    repository=repository,
                    status=JobStatus.QUEUED,
                )
                .on_conflict_do_nothing(
                    index_elements=[IngestionJobRow.repository_key],
                    index_where=text("status IN ('queued', 'running')"),
                )
                .returning(IngestionJobRow)
            )
            row = (await self._session.execute(stmt)).scalar_one_or_none()
            if row is not None:
                return _to_job(row), True
            active = await self._session.scalar(
                select(IngestionJobRow).where(
                    IngestionJobRow.repository_key == key,
                    IngestionJobRow.status.in_(ACTIVE_JOB_STATUSES),
                )
            )
            if active is not None:
                return _to_job(active), False
            # The active job finished in between: try to insert again.
        raise RuntimeError(f"Could not queue an import of {repository}")

    async def get(self, job_id: uuid.UUID) -> IngestionJob | None:
        row = await self._session.get(IngestionJobRow, job_id, populate_existing=True)
        return _to_job(row) if row is not None else None

    async def mark_running(self, job_id: uuid.UUID) -> None:
        await self._update(
            job_id, status=JobStatus.RUNNING, stage=JobStage.FETCHING, started_at=func.now()
        )

    async def set_stage(self, job_id: uuid.UUID, stage: JobStage, **counts: int) -> None:
        """Move to ``stage``, optionally setting ``*_count`` columns."""
        await self._update(job_id, stage=stage, **counts)

    async def set_repository(self, job_id: uuid.UUID, repository: str) -> None:
        """Store GitHub's canonical "owner/name" casing once it is known."""
        await self._update(job_id, repository=repository)

    async def add_embedded(self, job_id: uuid.UUID, count: int) -> None:
        await self._update(job_id, embedded_count=IngestionJobRow.embedded_count + count)

    async def mark_succeeded(
        self, job_id: uuid.UUID, snapshot_id: uuid.UUID, *, reused: bool
    ) -> None:
        await self._update(
            job_id,
            status=JobStatus.SUCCEEDED,
            stage=JobStage.DONE,
            snapshot_id=snapshot_id,
            reused_snapshot=reused,
            finished_at=func.now(),
        )

    async def mark_failed(self, job_id: uuid.UUID, error: str) -> None:
        await self._update(job_id, status=JobStatus.FAILED, error=error, finished_at=func.now())

    async def fail_interrupted(self) -> int:
        """Fail every queued or running job. Called at startup: imports run inside the
        API process, so jobs still active at that point were interrupted by a restart."""
        result = await self._session.execute(
            update(IngestionJobRow)
            .where(IngestionJobRow.status.in_(ACTIVE_JOB_STATUSES))
            .values(
                status=JobStatus.FAILED,
                error="The import was interrupted by a server restart. Please try again.",
                finished_at=func.now(),
            )
            .returning(IngestionJobRow.id)
        )
        return len(result.all())

    async def _update(self, job_id: uuid.UUID, **values: object) -> None:
        await self._session.execute(
            update(IngestionJobRow).where(IngestionJobRow.id == job_id).values(**values)
        )


def _to_job(row: IngestionJobRow) -> IngestionJob:
    return IngestionJob(
        id=row.id,
        repository=row.repository,
        status=JobStatus(row.status),
        stage=JobStage(row.stage) if row.stage else None,
        documents_count=row.documents_count,
        skipped_count=row.skipped_count,
        chunks_count=row.chunks_count,
        embedded_count=row.embedded_count,
        error=row.error,
        snapshot_id=row.snapshot_id,
        reused_snapshot=row.reused_snapshot,
        created_at=row.created_at,
        started_at=row.started_at,
        finished_at=row.finished_at,
    )

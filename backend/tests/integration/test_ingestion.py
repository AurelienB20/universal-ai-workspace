import logging
import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.fakes import DOCUMENTS, SHA, FakeEmbedder, FakeSource, fake_vector
from uaw.chunking.chunker import chunk_document
from uaw.chunking.lines import ChunkingConfig
from uaw.connectors.github.errors import RepositoryNotFoundError
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.jobs import IngestionJob, JobStage, JobStatus
from uaw.embeddings.base import embedding_text
from uaw.embeddings.errors import EmbeddingUnavailableError
from uaw.ingestion.pipeline import INTERNAL_ERROR_MESSAGE, IngestionPipeline
from uaw.storage.jobs import JobStore
from uaw.storage.models import ChunkRow, SnapshotRow
from uaw.storage.store import SnapshotStatus, SnapshotStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

Sessions = async_sessionmaker[AsyncSession]
REF = GitHubRepoRef(owner="octo", name="demo")
CONFIG = ChunkingConfig(max_chars=200, min_chars=50, overlap_lines=1)


def make_pipeline(
    sessions: Sessions, source: FakeSource | None = None, embedder: FakeEmbedder | None = None
) -> IngestionPipeline:
    return IngestionPipeline(
        sessions,
        source or FakeSource(),
        embedder or FakeEmbedder(),
        chunking=CONFIG,
        embed_batch_size=5,
    )


async def queue_job(sessions: Sessions, repository: str = "octo/demo") -> uuid.UUID:
    async with sessions.begin() as session:
        job, created = await JobStore(session).create_or_get_active(repository)
    assert created
    return job.id


async def get_job(sessions: Sessions, job_id: uuid.UUID) -> IngestionJob:
    async with sessions() as session:
        job = await JobStore(session).get(job_id)
    assert job is not None
    return job


async def count_rows(sessions: Sessions, table: type[object]) -> int:
    async with sessions() as session:
        return (await session.execute(select(func.count()).select_from(table))).scalar_one()


def expected_chunk_count() -> int:
    return sum(len(chunk_document(doc, CONFIG)) for doc in DOCUMENTS)


async def test_successful_import_produces_a_ready_fully_embedded_snapshot(
    session_factory: Sessions,
) -> None:
    embedder = FakeEmbedder()
    job_id = await queue_job(session_factory)

    await make_pipeline(session_factory, embedder=embedder).run(job_id, REF)

    job = await get_job(session_factory, job_id)
    chunks = expected_chunk_count()
    assert job.status is JobStatus.SUCCEEDED and job.stage is JobStage.DONE
    assert job.repository == "Octo/Demo"  # GitHub's canonical casing
    assert (job.documents_count, job.chunks_count, job.embedded_count) == (2, chunks, chunks)
    assert job.error is None and not job.reused_snapshot
    assert job.started_at is not None and job.finished_at is not None
    # Embedded in batches of at most 5, with the file path in each text.
    assert [len(call) for call in embedder.calls] == [5] * (chunks // 5) + (
        [chunks % 5] if chunks % 5 else []
    )
    assert all(text.startswith("File: ") for call in embedder.calls for text in call)

    async with session_factory() as session:
        snapshot = await session.get(SnapshotRow, job.snapshot_id)
        assert snapshot is not None
        assert (snapshot.status, snapshot.commit_sha) == (SnapshotStatus.READY, SHA)
        assert snapshot.embedding_model == "fake-embedder"
        # Each chunk got the vector of its own text (no mix-up between batches).
        for item in await SnapshotStore(session).list_chunks(snapshot.id):
            row = await session.get(ChunkRow, item.id)
            assert row is not None and row.embedding is not None
            assert list(row.embedding) == pytest.approx(fake_vector(embedding_text(item.chunk)))


async def test_reimporting_the_same_commit_reuses_the_snapshot(session_factory: Sessions) -> None:
    first_job = await queue_job(session_factory)
    await make_pipeline(session_factory).run(first_job, REF)
    embedder = FakeEmbedder()

    second_job = await queue_job(session_factory)
    await make_pipeline(session_factory, embedder=embedder).run(second_job, REF)

    first, second = (
        await get_job(session_factory, first_job),
        await get_job(session_factory, second_job),
    )
    assert second.status is JobStatus.SUCCEEDED and second.reused_snapshot
    assert second.snapshot_id == first.snapshot_id
    assert embedder.calls == []  # nothing re-embedded
    assert await count_rows(session_factory, SnapshotRow) == 1


async def test_new_commit_creates_a_new_snapshot(session_factory: Sessions) -> None:
    await make_pipeline(session_factory).run(await queue_job(session_factory), REF)

    job_id = await queue_job(session_factory)
    await make_pipeline(session_factory, FakeSource(sha="d" * 40)).run(job_id, REF)

    assert (await get_job(session_factory, job_id)).status is JobStatus.SUCCEEDED
    assert await count_rows(session_factory, SnapshotRow) == 2


async def test_embedding_failure_removes_the_partial_snapshot(session_factory: Sessions) -> None:
    error = EmbeddingUnavailableError("Voyage AI is unavailable or rate limited. Try again later.")
    embedder = FakeEmbedder(fail_on_call=2, error=error)
    job_id = await queue_job(session_factory)

    await make_pipeline(session_factory, embedder=embedder).run(job_id, REF)

    job = await get_job(session_factory, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error == str(error)
    assert job.embedded_count == 5  # the first batch was saved before the failure
    assert job.snapshot_id is None
    assert await count_rows(session_factory, SnapshotRow) == 0
    assert await count_rows(session_factory, ChunkRow) == 0


async def test_connector_errors_are_shown_to_users(session_factory: Sessions) -> None:
    error = RepositoryNotFoundError("Repository octo/demo was not found or is not accessible.")
    job_id = await queue_job(session_factory)

    await make_pipeline(session_factory, FakeSource(error=error)).run(job_id, REF)

    job = await get_job(session_factory, job_id)
    assert (job.status, job.stage, job.error) == (JobStatus.FAILED, JobStage.FETCHING, str(error))


async def test_unexpected_errors_are_hidden_from_users(
    session_factory: Sessions, caplog: pytest.LogCaptureFixture
) -> None:
    source = FakeSource(error=RuntimeError("password=hunter2 at db.internal:5432"))
    job_id = await queue_job(session_factory)

    with caplog.at_level(logging.ERROR):
        await make_pipeline(session_factory, source).run(job_id, REF)

    job = await get_job(session_factory, job_id)
    assert job.status is JobStatus.FAILED
    assert job.error == INTERNAL_ERROR_MESSAGE
    assert "hunter2" in caplog.text  # full detail stays in the server logs


async def test_leftover_indexing_snapshot_is_rebuilt(session_factory: Sessions) -> None:
    # Simulates a server restart in the middle of an import of the same commit.
    async with session_factory.begin() as session:
        store = SnapshotStore(session)
        repository_id = await store.upsert_repository((await FakeSource().fetch(REF)).info)
        stale_id = await store.create_snapshot(repository_id, SHA, embedding_model="fake-embedder")

    job_id = await queue_job(session_factory)
    await make_pipeline(session_factory).run(job_id, REF)

    job = await get_job(session_factory, job_id)
    assert job.status is JobStatus.SUCCEEDED and not job.reused_snapshot
    assert job.snapshot_id != stale_id
    assert await count_rows(session_factory, SnapshotRow) == 1


async def test_empty_repository_is_imported(session_factory: Sessions) -> None:
    job_id = await queue_job(session_factory)

    await make_pipeline(session_factory, FakeSource(documents=[])).run(job_id, REF)

    job = await get_job(session_factory, job_id)
    assert (job.status, job.chunks_count) == (JobStatus.SUCCEEDED, 0)


# --- JobStore ---------------------------------------------------------------------


async def test_only_one_active_job_per_repository(session_factory: Sessions) -> None:
    first_id = await queue_job(session_factory, "Octo/Demo")

    async with session_factory.begin() as session:
        job, created = await JobStore(session).create_or_get_active("octo/DEMO")
    assert (job.id, created) == (first_id, False)

    async with session_factory.begin() as session:
        await JobStore(session).mark_failed(first_id, "boom")
        job, created = await JobStore(session).create_or_get_active("octo/demo")
    assert created and job.id != first_id


async def test_interrupted_jobs_are_failed_at_startup(session_factory: Sessions) -> None:
    queued = await queue_job(session_factory, "octo/a")
    running = await queue_job(session_factory, "octo/b")
    done = await queue_job(session_factory, "octo/c")
    async with session_factory.begin() as session:
        jobs = JobStore(session)
        await jobs.mark_running(running)
        await jobs.mark_failed(done, "earlier failure")

        assert await jobs.fail_interrupted() == 2

    for job_id in (queued, running):
        job = await get_job(session_factory, job_id)
        assert job.status is JobStatus.FAILED and "restart" in (job.error or "")
    assert (await get_job(session_factory, done)).error == "earlier failure"

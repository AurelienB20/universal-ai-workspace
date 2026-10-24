"""Import pipeline: repository -> chunks -> embeddings -> searchable snapshot.

Transactions are deliberately short:
1. chunks are saved in one transaction (all or nothing);
2. embeddings are saved batch by batch, so progress is visible and no transaction
   stays open during slow API calls;
3. the snapshot becomes "ready" (searchable) only once every chunk has a vector,
   and the oldest snapshots of the repository are deleted in the same transaction.
If anything fails, the incomplete snapshot is deleted and the job records a
user-facing error message.
"""

import asyncio
import logging
import uuid
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.chunking.chunker import chunk_document
from uaw.chunking.lines import ChunkingConfig
from uaw.connectors.github.connector import FetchedRepository
from uaw.connectors.github.errors import GitHubConnectorError
from uaw.connectors.github.url import GitHubRepoRef
from uaw.domain.chunks import Chunk
from uaw.domain.documents import SourceDocument
from uaw.domain.jobs import JobStage
from uaw.embeddings.base import Embedder, embedding_text
from uaw.embeddings.errors import EmbeddingError
from uaw.storage.jobs import JobStore
from uaw.storage.store import SnapshotStatus, SnapshotStore

logger = logging.getLogger(__name__)

# Errors whose message is written for end users. Anything else is a bug or an
# infrastructure failure: it is logged in full, and users get a generic message.
USER_FACING_ERRORS = (GitHubConnectorError, EmbeddingError)
INTERNAL_ERROR_MESSAGE = "The import failed because of an internal error."


class RepositorySource(Protocol):
    async def fetch(self, ref: GitHubRepoRef) -> FetchedRepository: ...


class IngestionPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        source: RepositorySource,
        embedder: Embedder,
        *,
        chunking: ChunkingConfig | None = None,
        embed_batch_size: int = 128,
        keep_snapshots: int = 2,
    ) -> None:
        self._sessions = session_factory
        self._source = source
        self._embedder = embedder
        self._chunking = chunking or ChunkingConfig()
        self._embed_batch_size = embed_batch_size
        self._keep_snapshots = keep_snapshots

    async def run(self, job_id: uuid.UUID, ref: GitHubRepoRef) -> None:
        """Run one import to completion. Failures are recorded on the job, not raised."""
        snapshot_id: uuid.UUID | None = None
        try:
            async with self._sessions.begin() as session:
                await JobStore(session).mark_running(job_id)

            fetched = await self._source.fetch(ref)
            async with self._sessions.begin() as session:
                jobs = JobStore(session)
                await jobs.set_repository(job_id, fetched.info.ref.full_name)
                await jobs.set_stage(
                    job_id,
                    JobStage.CHUNKING,
                    documents_count=len(fetched.documents),
                    skipped_count=len(fetched.skipped),
                )

            reused_id = await self._find_reusable_snapshot(job_id, fetched)
            if reused_id is not None:
                logger.info("Reusing snapshot %s for %s", reused_id, fetched.info.ref.full_name)
                return

            # Chunking is CPU-bound: keep it off the event loop.
            chunked = await asyncio.to_thread(_chunk_all, fetched.documents, self._chunking)
            snapshot_id, pending = await self._save_chunks(job_id, fetched, chunked)
            await self._embed(job_id, pending)

            async with self._sessions.begin() as session:
                store = SnapshotStore(session)
                await store.mark_snapshot_ready(snapshot_id)
                pruned = await store.prune_snapshots(snapshot_id, keep=self._keep_snapshots)
                await JobStore(session).mark_succeeded(job_id, snapshot_id, reused=False)
            logger.info(
                "Imported %s@%s: %d chunks (%d old snapshots deleted)",
                fetched.info.ref.full_name,
                fetched.commit_sha,
                len(pending),
                pruned,
            )
        except Exception as exc:
            await self._fail(job_id, snapshot_id, exc)

    async def _find_reusable_snapshot(
        self, job_id: uuid.UUID, fetched: FetchedRepository
    ) -> uuid.UUID | None:
        """Reuse a ready snapshot of the same commit and model; drop a stale one."""
        async with self._sessions.begin() as session:
            store = SnapshotStore(session)
            repository_id = await store.upsert_repository(fetched.info)
            existing = await store.find_snapshot(repository_id, fetched.commit_sha)
            if existing is None:
                return None
            if (
                existing.status is SnapshotStatus.READY
                and existing.embedding_model == self._embedder.model
            ):
                await JobStore(session).mark_succeeded(job_id, existing.id, reused=True)
                return existing.id
            # Left over by an interrupted import (only one import per repository can
            # run at a time), or embedded with another model: rebuild it.
            await store.delete_snapshot(existing.id)
            return None

    async def _save_chunks(
        self,
        job_id: uuid.UUID,
        fetched: FetchedRepository,
        chunked: list[tuple[SourceDocument, list[Chunk]]],
    ) -> tuple[uuid.UUID, list[tuple[uuid.UUID, str]]]:
        """Save documents and chunks in one transaction. Returns the texts to embed."""
        async with self._sessions.begin() as session:
            store = SnapshotStore(session)
            repository_id = await store.upsert_repository(fetched.info)
            snapshot_id = await store.create_snapshot(
                repository_id, fetched.commit_sha, embedding_model=self._embedder.model
            )
            pending: list[tuple[uuid.UUID, str]] = []
            for document, chunks in chunked:
                chunk_ids = await store.add_document(snapshot_id, document, chunks)
                pending.extend(zip(chunk_ids, map(embedding_text, chunks), strict=True))
            await JobStore(session).set_stage(job_id, JobStage.EMBEDDING, chunks_count=len(pending))
        return snapshot_id, pending

    async def _embed(self, job_id: uuid.UUID, pending: list[tuple[uuid.UUID, str]]) -> None:
        for start in range(0, len(pending), self._embed_batch_size):
            batch = pending[start : start + self._embed_batch_size]
            vectors = await self._embedder.embed_documents([text for _, text in batch])
            async with self._sessions.begin() as session:
                await SnapshotStore(session).set_embeddings(
                    {chunk_id: vector for (chunk_id, _), vector in zip(batch, vectors, strict=True)}
                )
                await JobStore(session).add_embedded(job_id, len(batch))

    async def _fail(self, job_id: uuid.UUID, snapshot_id: uuid.UUID | None, exc: Exception) -> None:
        if isinstance(exc, USER_FACING_ERRORS):
            logger.warning("Import job %s failed: %s", job_id, exc)
            message = str(exc)
        else:
            logger.exception("Import job %s failed unexpectedly", job_id)
            message = INTERNAL_ERROR_MESSAGE
        try:
            async with self._sessions.begin() as session:
                if snapshot_id is not None:
                    await SnapshotStore(session).delete_snapshot(snapshot_id)
                await JobStore(session).mark_failed(job_id, message)
        except Exception:
            # Typically the database itself is down. The job stays "running" and is
            # marked as interrupted at the next startup.
            logger.exception("Could not record the failure of import job %s", job_id)


def _chunk_all(
    documents: list[SourceDocument], config: ChunkingConfig
) -> list[tuple[SourceDocument, list[Chunk]]]:
    return [(document, chunk_document(document, config)) for document in documents]

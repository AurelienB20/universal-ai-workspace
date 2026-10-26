"""Runs imports in the background, inside the API process.

Trade-off: no extra infrastructure (queue, worker) for the MVP, at the price that a
restart interrupts running imports. Those jobs are marked as failed at the next
startup, and users can simply import again. This assumes a single API process.

Imports by visitors of the public demo run one at a time, under the visitor policy,
in their own lane: they never hold up the admin's imports.
"""

import asyncio
import logging
import uuid
from typing import Protocol

from uaw.connectors.github.url import GitHubRepoRef
from uaw.ingestion.pipeline import ImportPolicy
from uaw.usage.tracker import UsageTracker

logger = logging.getLogger(__name__)


class Pipeline(Protocol):
    async def run(
        self, job_id: uuid.UUID, ref: GitHubRepoRef, policy: ImportPolicy | None = None
    ) -> None: ...


class IngestionRunner:
    def __init__(
        self,
        pipeline: Pipeline,
        *,
        max_concurrent: int,
        usage: UsageTracker | None = None,
        visitor_policy: ImportPolicy | None = None,
    ) -> None:
        self._pipeline = pipeline
        self._usage = usage
        self._visitor_policy = visitor_policy or ImportPolicy()
        # Imports beyond the limit wait in the "queued" state.
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._visitor_semaphore = asyncio.Semaphore(1)
        # Strong references: the event loop only keeps weak references to tasks.
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, job_id: uuid.UUID, ref: GitHubRepoRef, *, visitor: bool = False) -> None:
        run = self._run_for_visitor(job_id, ref) if visitor else self._run(job_id, ref, None)
        task = asyncio.create_task(run, name=f"import-{job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run_for_visitor(self, job_id: uuid.UUID, ref: GitHubRepoRef) -> None:
        async with self._visitor_semaphore:
            await self._run(job_id, ref, self._visitor_policy)

    async def _run(
        self, job_id: uuid.UUID, ref: GitHubRepoRef, policy: ImportPolicy | None
    ) -> None:
        async with self._semaphore:
            if self._usage is None:
                await self._pipeline.run(job_id, ref, policy)
                return
            async with self._usage.track("import", ref.full_name):
                await self._pipeline.run(job_id, ref, policy)

    async def wait_idle(self) -> None:
        """Wait until every submitted import has finished (used by tests)."""
        while self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    async def shutdown(self) -> None:
        if self._tasks:
            logger.warning("Cancelling %d running imports", len(self._tasks))
        for task in self._tasks:
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

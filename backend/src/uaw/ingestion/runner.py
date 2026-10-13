"""Runs imports in the background, inside the API process.

Trade-off: no extra infrastructure (queue, worker) for the MVP, at the price that a
restart interrupts running imports. Those jobs are marked as failed at the next
startup, and users can simply import again. This assumes a single API process.
"""

import asyncio
import logging
import uuid
from typing import Protocol

from uaw.connectors.github.url import GitHubRepoRef

logger = logging.getLogger(__name__)


class Pipeline(Protocol):
    async def run(self, job_id: uuid.UUID, ref: GitHubRepoRef) -> None: ...


class IngestionRunner:
    def __init__(self, pipeline: Pipeline, *, max_concurrent: int) -> None:
        self._pipeline = pipeline
        # Imports beyond the limit wait in the "queued" state.
        self._semaphore = asyncio.Semaphore(max_concurrent)
        # Strong references: the event loop only keeps weak references to tasks.
        self._tasks: set[asyncio.Task[None]] = set()

    def submit(self, job_id: uuid.UUID, ref: GitHubRepoRef) -> None:
        task = asyncio.create_task(self._run(job_id, ref), name=f"import-{job_id}")
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def _run(self, job_id: uuid.UUID, ref: GitHubRepoRef) -> None:
        async with self._semaphore:
            await self._pipeline.run(job_id, ref)

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

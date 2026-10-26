import asyncio
import uuid

import pytest

from uaw.connectors.github.url import GitHubRepoRef
from uaw.ingestion.pipeline import ImportPolicy
from uaw.ingestion.runner import IngestionRunner

pytestmark = pytest.mark.anyio

REF = GitHubRepoRef(owner="octo", name="demo")


class BlockingPipeline:
    """Records concurrency; each run waits until the test releases it."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.running = 0
        self.max_running = 0
        self.finished: list[uuid.UUID] = []
        self.cancelled: list[uuid.UUID] = []
        self.policies: dict[uuid.UUID, ImportPolicy | None] = {}

    async def run(
        self, job_id: uuid.UUID, ref: GitHubRepoRef, policy: ImportPolicy | None = None
    ) -> None:
        self.policies[job_id] = policy
        self.running += 1
        self.max_running = max(self.max_running, self.running)
        try:
            await self.release.wait()
            self.finished.append(job_id)
        except asyncio.CancelledError:
            self.cancelled.append(job_id)
            raise
        finally:
            self.running -= 1


async def test_limits_concurrent_imports() -> None:
    pipeline = BlockingPipeline()
    runner = IngestionRunner(pipeline, max_concurrent=2)
    job_ids = [uuid.uuid4() for _ in range(5)]

    for job_id in job_ids:
        runner.submit(job_id, REF)
    await asyncio.sleep(0.01)
    assert pipeline.running == 2

    pipeline.release.set()
    await runner.wait_idle()

    assert pipeline.max_running == 2
    assert sorted(pipeline.finished) == sorted(job_ids)


async def test_shutdown_cancels_running_imports() -> None:
    pipeline = BlockingPipeline()
    runner = IngestionRunner(pipeline, max_concurrent=1)
    first, second = uuid.uuid4(), uuid.uuid4()
    runner.submit(first, REF)
    runner.submit(second, REF)
    await asyncio.sleep(0.01)

    await runner.shutdown()

    # The running import is cancelled; the queued one never starts.
    assert pipeline.cancelled == [first]
    assert pipeline.finished == []
    await runner.wait_idle()  # nothing left


async def test_visitor_imports_run_one_at_a_time_beside_the_admin_ones() -> None:
    pipeline = BlockingPipeline()
    policy = ImportPolicy(max_embedding_tokens=123)
    runner = IngestionRunner(pipeline, max_concurrent=3, visitor_policy=policy)
    visitors = [uuid.uuid4() for _ in range(3)]
    admin = uuid.uuid4()

    for job_id in visitors:
        runner.submit(job_id, REF, visitor=True)
    runner.submit(admin, REF)
    await asyncio.sleep(0.01)

    # One visitor import and the admin's: the other visitor imports wait.
    assert pipeline.running == 2
    pipeline.release.set()
    await runner.wait_idle()
    assert sorted(pipeline.finished) == sorted([*visitors, admin])
    assert {pipeline.policies[job_id] for job_id in visitors} == {policy}
    assert pipeline.policies[admin] is None

import asyncio
from datetime import timedelta

import pytest

from uaw.maintenance import run_periodically

pytestmark = pytest.mark.anyio


async def test_a_failed_run_does_not_stop_the_next_ones() -> None:
    runs: list[int] = []

    async def task() -> None:
        runs.append(len(runs))
        if len(runs) == 1:
            raise RuntimeError("database down")

    running = asyncio.create_task(run_periodically(task, timedelta(milliseconds=1)))
    while len(runs) < 3:
        await asyncio.sleep(0.001)
    running.cancel()

    with pytest.raises(asyncio.CancelledError):
        await running
    assert runs[:3] == [0, 1, 2]

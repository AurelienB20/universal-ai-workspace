import asyncio

import pytest

from uaw.usage.meter import ModelUsage, metering, record_usage

pytestmark = pytest.mark.anyio


def test_usage_is_summed_per_model() -> None:
    with metering() as meter:
        record_usage("voyage", "voyage-code-3", input_tokens=10)
        record_usage("voyage", "voyage-code-3", input_tokens=5)
        record_usage("anthropic", "claude-opus-5-5", input_tokens=100, output_tokens=20)

    assert meter.usages == [
        ModelUsage("voyage", "voyage-code-3", requests=2, input_tokens=15),
        ModelUsage("anthropic", "claude-opus-5-5", requests=1, input_tokens=100, output_tokens=20),
    ]


def test_usage_outside_metering_is_ignored() -> None:
    record_usage("voyage", "voyage-code-3", input_tokens=10)  # must not fail

    with metering() as meter:
        pass
    assert meter.usages == []


async def test_tasks_count_on_the_meter_of_the_operation_that_started_them() -> None:
    async def work(tokens: int) -> None:
        await asyncio.sleep(0)
        record_usage("voyage", "voyage-code-3", input_tokens=tokens)

    async def operation(tokens: int) -> int:
        with metering() as meter:
            await asyncio.gather(
                work(tokens), asyncio.to_thread(record_usage, "voyage", "m", input_tokens=1)
            )
        return sum(usage.input_tokens for usage in meter.usages)

    # Two operations running at the same time never mix their counts.
    assert list(await asyncio.gather(operation(10), operation(1000))) == [11, 1001]

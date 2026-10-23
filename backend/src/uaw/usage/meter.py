"""Counts the tokens used by one operation (an HTTP request, an import).

The provider clients call ``record_usage`` after each API call. The tokens go to the
meter of the current operation, if one is active: ``metering()`` stores it in a
context variable, which asyncio copies into the tasks and threads the operation
starts. The clients need no extra parameter, and two imports running at the same
time never mix their counts.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Literal

Provider = Literal["voyage", "anthropic"]


@dataclass
class ModelUsage:
    provider: Provider
    model: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class UsageMeter:
    _by_model: dict[tuple[Provider, str], ModelUsage] = field(default_factory=dict)

    def add(self, provider: Provider, model: str, *, input_tokens: int, output_tokens: int) -> None:
        usage = self._by_model.setdefault((provider, model), ModelUsage(provider, model))
        usage.requests += 1
        usage.input_tokens += input_tokens
        usage.output_tokens += output_tokens

    @property
    def usages(self) -> list[ModelUsage]:
        return list(self._by_model.values())


_current_meter: ContextVar[UsageMeter | None] = ContextVar("uaw_usage_meter", default=None)


@contextmanager
def metering() -> Iterator[UsageMeter]:
    """Count the tokens used inside the block, including by the tasks it starts."""
    meter = UsageMeter()
    token = _current_meter.set(meter)
    try:
        yield meter
    finally:
        _current_meter.reset(token)


def record_usage(
    provider: Provider, model: str, *, input_tokens: int, output_tokens: int = 0
) -> None:
    """Add one API call to the current operation's meter (no-op outside ``metering``)."""
    meter = _current_meter.get()
    if meter is not None:
        meter.add(provider, model, input_tokens=input_tokens, output_tokens=output_tokens)

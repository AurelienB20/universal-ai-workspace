"""Per-client rate limits (token bucket), kept in memory.

Trade-off: no extra infrastructure (Redis) for the MVP. Each API process counts on
its own and the counts restart with the process, which is enough for one instance.
Behind a reverse proxy, run uvicorn with ``--proxy-headers`` so that the client
address is the real one, not the proxy's.
"""

import math
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Literal

from fastapi import HTTPException, Request, status

from uaw.config import Settings

LimitName = Literal["imports", "visitor_imports", "search", "ask"]
Clock = Callable[[], float]


class RateLimiter:
    """At most ``limit`` requests per ``period_seconds`` per client, refilled steadily."""

    def __init__(
        self,
        limit: int,
        period_seconds: float,
        *,
        max_clients: int = 10_000,
        clock: Clock = time.monotonic,
    ) -> None:
        self._capacity = float(limit)
        self._refill_per_second = limit / period_seconds
        self._max_clients = max_clients
        self._clock = clock
        # client -> (available tokens, last update). Insertion order = least recently
        # seen first, so the oldest entry is dropped when the table is full.
        self._buckets: dict[str, tuple[float, float]] = {}

    def acquire(self, client: str) -> float:
        """Take one request. Returns 0 if allowed, else the seconds to wait."""
        now = self._clock()
        tokens, updated = self._buckets.pop(client, (self._capacity, now))
        tokens = min(self._capacity, tokens + (now - updated) * self._refill_per_second)
        wait = 0.0
        if tokens >= 1:
            tokens -= 1
        else:
            wait = (1 - tokens) / self._refill_per_second
        self._buckets[client] = (tokens, now)
        if len(self._buckets) > self._max_clients:
            del self._buckets[next(iter(self._buckets))]
        return wait


def build_rate_limiters(settings: Settings) -> dict[LimitName, RateLimiter]:
    configured: dict[LimitName, tuple[int, float]] = {
        "imports": (settings.rate_limit_imports_per_hour, 3600),
        "visitor_imports": (settings.rate_limit_visitor_imports_per_day, 86_400),
        "search": (settings.rate_limit_search_per_minute, 60),
        "ask": (settings.rate_limit_ask_per_minute, 60),
    }
    return {
        name: RateLimiter(limit, period)
        for name, (limit, period) in configured.items()
        if limit > 0
    }


def rate_limited(name: LimitName) -> Callable[[Request], None]:
    """Route dependency enforcing the ``name`` limit for the calling client."""

    def dependency(request: Request) -> None:
        enforce_rate_limit(request, name)

    return dependency


def enforce_rate_limit(request: Request, name: LimitName) -> None:
    """Count one request against the ``name`` limit of the calling client; ``429``
    once it is reached."""
    limiter: RateLimiter | None = request.app.state.rate_limiters.get(name)
    if limiter is None:
        return
    client = request.client.host if request.client else "unknown"
    wait = limiter.acquire(client)
    if wait > 0:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests. Try again later.",
            headers={"Retry-After": str(math.ceil(wait))},
        )


class ConcurrencyLimiter:
    """At most ``limit`` operations at a time, all clients combined. An operation that
    finds every slot taken is refused at once: queueing would only hold connections
    open while the clients wait."""

    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._running = 0

    @contextmanager
    def slot(self, retry_after_seconds: int = 5) -> Iterator[None]:
        # No await between the check and the increment: on one event loop, two
        # requests cannot both take the last slot.
        if self._running >= self._limit:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="The server is busy answering other questions. Try again shortly.",
                headers={"Retry-After": str(retry_after_seconds)},
            )
        self._running += 1
        try:
            yield
        finally:
            self._running -= 1

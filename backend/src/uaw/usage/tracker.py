"""Records the tokens used by each operation and enforces the daily budgets."""

import logging
import uuid
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.storage.usage import Operation, UsageStore
from uaw.usage.meter import ModelUsage, Provider, metering

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


# When the budget is only held by operations in progress, it frees up within seconds.
BUSY_RETRY_AFTER_SECONDS = 10


class BudgetExceededError(Exception):
    """The daily token budget of a provider is spent, or held by operations in progress."""

    def __init__(self, provider: Provider, retry_after_seconds: int, *, busy: bool = False) -> None:
        if busy:
            message = f"The usage limit of this server is reached for now ({provider})."
        else:
            message = f"The daily usage limit of this server is reached ({provider})."
        super().__init__(message)
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds


class UsageTracker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        daily_budgets: Mapping[Provider, int],
        reservation_ttl: timedelta = timedelta(minutes=10),
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        # 0 = no budget for that provider.
        self._budgets = {provider: budget for provider, budget in daily_budgets.items() if budget}
        # Longer than any operation (LLM timeout and retries), so that only the
        # reservation of a crashed process can expire.
        self._reservation_ttl = reservation_ttl
        self._clock = clock

    def _spent(self, provider: Provider, used: int, now: datetime) -> BudgetExceededError:
        logger.warning(
            "Daily %s token budget spent (%d/%d)", provider, used, self._budgets[provider]
        )
        retry_after = _next_midnight(now) - now
        return BudgetExceededError(provider, int(retry_after.total_seconds()) + 1)

    async def ensure_within_budget(self, *providers: Provider) -> None:
        """Raise ``BudgetExceededError`` if a provider's budget for today is spent.

        A plain check, for operations whose cost cannot be estimated in advance
        (imports, admin only): such an operation can overshoot the budget by its own
        usage. Questions and searches use ``reserve`` instead.
        """
        limited = [provider for provider in providers if provider in self._budgets]
        if not limited:
            return
        now = self._clock()
        async with self._sessions() as session:
            store = UsageStore(session)
            for provider in limited:
                used = await store.tokens_since(provider, _midnight(now))
                if used >= self._budgets[provider]:
                    raise self._spent(provider, used, now)

    @asynccontextmanager
    async def reserve(self, estimates: Mapping[Provider, int]) -> AsyncIterator[None]:
        """Set aside the worst-case tokens of an operation for the duration of the block.

        The check and the reservation happen under a database lock, so concurrent
        requests can never pass together more than the budget: with a 10,000-token
        budget and 10,000-token estimates, one of two simultaneous questions is refused.
        Raises ``BudgetExceededError`` before the block runs.
        """
        limited = {
            provider: tokens
            for provider, tokens in estimates.items()
            if provider in self._budgets and tokens > 0
        }
        if not limited:
            yield
            return
        now = self._clock()
        reservation_ids = []
        # Raising inside the transaction rolls back the reservations already made.
        async with self._sessions.begin() as session:
            store = UsageStore(session)
            # A fixed lock order: two requests can never wait for each other's lock.
            for provider in sorted(limited):
                needed, budget = limited[provider], self._budgets[provider]
                await store.lock_budget(provider)
                used = await store.tokens_since(provider, _midnight(now))
                if used + needed > budget:
                    raise self._spent(provider, used, now)
                reserved = await store.reserved_tokens(provider, now)
                if used + reserved + needed > budget:
                    raise BudgetExceededError(provider, BUSY_RETRY_AFTER_SECONDS, busy=True)
                reservation_ids.append(
                    await store.add_reservation(provider, needed, now + self._reservation_ttl)
                )
        try:
            yield
        finally:
            await self._release(reservation_ids)

    async def _release(self, reservation_ids: list[uuid.UUID]) -> None:
        try:
            async with self._sessions.begin() as session:
                await UsageStore(session).delete_reservations(
                    reservation_ids, expired_before=self._clock()
                )
        except Exception:
            # The reservations expire on their own: do not fail the operation for this.
            logger.exception("Could not release budget reservations %s", reservation_ids)

    @asynccontextmanager
    async def track(self, operation: Operation, repository: str) -> AsyncIterator[None]:
        """Count the tokens used inside the block and save them, even if it fails:
        a failed operation may already have been billed."""
        with metering() as meter:
            try:
                yield
            finally:
                await self._save(operation, repository, meter.usages)

    async def _save(self, operation: Operation, repository: str, usages: list[ModelUsage]) -> None:
        if not usages:
            return
        for usage in usages:
            logger.info(
                "Usage: %s on %s, %s %s: %d requests, %d input + %d output tokens",
                operation,
                repository,
                usage.provider,
                usage.model,
                usage.requests,
                usage.input_tokens,
                usage.output_tokens,
            )
        try:
            async with self._sessions.begin() as session:
                await UsageStore(session).add(operation, repository, usages)
        except Exception:
            # The answer or import itself succeeded: do not fail it for bookkeeping.
            logger.exception("Could not record the token usage of %s on %s", operation, repository)


def _midnight(now: datetime) -> datetime:
    """Start of the current UTC day: budgets are daily."""
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def _next_midnight(now: datetime) -> datetime:
    return _midnight(now) + timedelta(days=1)

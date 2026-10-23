"""Records the tokens used by each operation and enforces the daily budgets."""

import logging
from collections.abc import AsyncIterator, Callable, Mapping
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.storage.usage import Operation, UsageStore
from uaw.usage.meter import ModelUsage, Provider, metering

logger = logging.getLogger(__name__)

Clock = Callable[[], datetime]


class BudgetExceededError(Exception):
    """The daily token budget of a provider is spent."""

    def __init__(self, provider: Provider, retry_after_seconds: int) -> None:
        super().__init__(f"The daily usage limit of this server is reached ({provider}).")
        self.provider = provider
        self.retry_after_seconds = retry_after_seconds


class UsageTracker:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        daily_budgets: Mapping[Provider, int],
        clock: Clock = lambda: datetime.now(UTC),
    ) -> None:
        self._sessions = session_factory
        # 0 = no budget for that provider.
        self._budgets = {provider: budget for provider, budget in daily_budgets.items() if budget}
        self._clock = clock

    async def ensure_within_budget(self, *providers: Provider) -> None:
        """Raise ``BudgetExceededError`` if a provider's budget for today is spent.

        Checked before an operation starts, so an operation can overshoot the budget
        by its own usage: budgets are a safety net, not exact quotas.
        """
        limited = [provider for provider in providers if provider in self._budgets]
        if not limited:
            return
        now = self._clock()
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        async with self._sessions() as session:
            store = UsageStore(session)
            for provider in limited:
                used = await store.tokens_since(provider, midnight)
                if used >= self._budgets[provider]:
                    logger.warning(
                        "Daily %s token budget spent (%d/%d)",
                        provider,
                        used,
                        self._budgets[provider],
                    )
                    retry_after = midnight + timedelta(days=1) - now
                    raise BudgetExceededError(provider, int(retry_after.total_seconds()) + 1)

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

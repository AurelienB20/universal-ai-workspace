"""Daily budgets and usage recording, as used by the routes."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import HTTPException, status

from uaw.services import Services
from uaw.storage.usage import Operation
from uaw.usage.meter import Provider
from uaw.usage.tracker import BudgetExceededError


async def ensure_within_budget(services: Services, *providers: Provider) -> None:
    if services.usage is None:
        return
    try:
        await services.usage.ensure_within_budget(*providers)
    except BudgetExceededError as exc:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
            headers={"Retry-After": str(exc.retry_after_seconds)},
        ) from exc


@asynccontextmanager
async def tracked(services: Services, operation: Operation, repository: str) -> AsyncIterator[None]:
    """Record the tokens used by the block."""
    if services.usage is None:
        yield
        return
    async with services.usage.track(operation, repository):
        yield

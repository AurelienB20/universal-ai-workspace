"""Background upkeep of the public demo.

Repositories imported by visitors are deleted once no visitor may read them any more.
The task runs inside the API process, like imports: no extra scheduler to operate.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable, Collection
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from uaw.storage.jobs import JobStore
from uaw.storage.store import SnapshotStore
from uaw.storage.visitors import VisitorAccessStore

logger = logging.getLogger(__name__)


async def remove_abandoned_repositories(
    session_factory: async_sessionmaker[AsyncSession], keep: Collection[str]
) -> list[str]:
    """Delete the ended visitor accesses, then the repositories that only visitors
    imported and that nobody may read any more, except those in ``keep`` (the
    DEMO_REPOSITORIES). Returns the deleted repositories. Token usage is kept."""
    async with session_factory.begin() as session:
        # Under the visitor import lock: no visitor gains access to a repository while
        # it is being deleted.
        await JobStore(session).lock_visitor_imports()
        access = VisitorAccessStore(session)
        expired = await access.delete_expired()
        store = SnapshotStore(session)
        # delete_repository skips a repository whose import is queued or running.
        deleted = [
            key
            for key in await access.abandoned_repositories(keep)
            if await store.delete_repository(key)
        ]
    if expired or deleted:
        logger.info(
            "Visitor cleanup: %d accesses ended, %d repositories deleted %s",
            expired,
            len(deleted),
            deleted,
        )
    return deleted


async def run_periodically(task: Callable[[], Awaitable[object]], interval: timedelta) -> None:
    """Run ``task`` now, then every ``interval``, until cancelled. A failed run is
    logged and retried at the next interval."""
    while True:
        try:
            await task()
        except Exception:
            logger.exception("Background task %s failed", getattr(task, "__name__", task))
        await asyncio.sleep(interval.total_seconds())

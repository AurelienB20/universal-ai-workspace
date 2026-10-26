"""Repositories imported by visitors are deleted once nobody may read them any more."""

import uuid
from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.integration.test_search import add_snapshot, vector
from uaw.connectors.github.url import GitHubRepoRef
from uaw.maintenance import remove_abandoned_repositories
from uaw.storage.jobs import JobStore
from uaw.storage.models import RepositoryRow, VisitorRepositoryRow
from uaw.storage.visitors import VisitorAccessStore

pytestmark = [pytest.mark.db, pytest.mark.anyio]

Sessions = async_sessionmaker[AsyncSession]
ANN = uuid.UUID("11111111-1111-4111-8111-111111111111")
BOB = uuid.UUID("22222222-2222-4222-8222-222222222222")
EXPIRED = timedelta(seconds=-1)
DAY = timedelta(hours=24)


async def add(
    sessions: Sessions,
    name: str,
    *,
    imported_by: list[uuid.UUID | None],
    grants: dict[uuid.UUID, timedelta] | None = None,
    active: bool = False,
    asked_as: str | None = None,
) -> None:
    """A repository octo/<name>, its import jobs (one per entry of ``imported_by``,
    None = the admin) and its visitor accesses."""
    async with sessions.begin() as session:
        await add_snapshot(
            session,
            repository=GitHubRepoRef(owner="octo", name=name),
            files={"a.py": [vector((0, 1.0))]},
        )
        jobs = JobStore(session)
        for visitor_id in imported_by:
            job, _ = await jobs.create_or_get_active(asked_as or f"octo/{name}", visitor_id)
            if asked_as:
                await jobs.set_repository(job.id, f"octo/{name}")
            if not active:
                await jobs.mark_failed(job.id, "finished")
        for visitor_id, ttl in (grants or {}).items():
            await VisitorAccessStore(session).grant(visitor_id, f"octo/{name}", ttl)


async def repositories(sessions: Sessions) -> list[str]:
    async with sessions() as session:
        return sorted((await session.scalars(select(RepositoryRow.key))).all())


async def test_only_abandoned_visitor_repositories_are_deleted(session_factory: Sessions) -> None:
    await add(session_factory, "expired", imported_by=[ANN], grants={ANN: EXPIRED})
    await add(session_factory, "no-access", imported_by=[ANN])
    await add(session_factory, "read", imported_by=[ANN], grants={ANN: EXPIRED, BOB: DAY})
    await add(session_factory, "admin", imported_by=[ANN, None], grants={ANN: EXPIRED})
    await add(session_factory, "no-job", imported_by=[])
    await add(session_factory, "demo", imported_by=[ANN], grants={ANN: EXPIRED})
    await add(session_factory, "importing", imported_by=[ANN], active=True)
    await add(session_factory, "renamed", imported_by=[ANN], asked_as="octo/old-name")

    deleted = await remove_abandoned_repositories(session_factory, keep={"octo/demo"})

    assert sorted(deleted) == ["octo/expired", "octo/no-access", "octo/renamed"]
    assert await repositories(session_factory) == [
        "octo/admin",
        "octo/demo",
        "octo/importing",
        "octo/no-job",
        "octo/read",
    ]
    async with session_factory() as session:
        accesses = (
            await session.execute(
                select(VisitorRepositoryRow.visitor_id, VisitorRepositoryRow.repository_key)
            )
        ).all()
    # Only the access that has not ended is left.
    assert accesses == [(BOB, "octo/read")]


async def test_nothing_to_clean(session_factory: Sessions) -> None:
    assert await remove_abandoned_repositories(session_factory, keep=frozenset()) == []

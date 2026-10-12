import asyncio
from collections.abc import Callable

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import Connection, inspect
from sqlalchemy.ext.asyncio import create_async_engine

from tests.integration.conftest import alembic_config
from uaw.storage.models import Base

# Synchronous tests: Alembic's env.py starts its own event loop.
pytestmark = pytest.mark.db


def run_on_database[T](url: str, fn: Callable[[Connection], T]) -> T:
    async def main() -> T:
        engine = create_async_engine(url)
        async with engine.connect() as connection:
            result = await connection.run_sync(fn)
        await engine.dispose()
        return result

    return asyncio.run(main())


def schema_diff(connection: Connection) -> list[object]:
    return list(compare_metadata(MigrationContext.configure(connection), Base.metadata))


def table_names(connection: Connection) -> set[str]:
    return set(inspect(connection).get_table_names())


def test_migrations_match_the_models(database_url: str) -> None:
    # Fails if a model changes without a migration (or the other way round).
    assert run_on_database(database_url, schema_diff) == []


def test_migrations_can_be_reverted_and_reapplied(database_url: str) -> None:
    config = alembic_config()

    command.downgrade(config, "base")
    assert run_on_database(database_url, table_names) == {"alembic_version"}

    command.upgrade(config, "head")
    assert {"repositories", "snapshots", "documents", "chunks"} <= run_on_database(
        database_url, table_names
    )

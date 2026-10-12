"""Alembic environment: runs migrations with the application's async engine settings.

The database URL comes from the application settings (``DATABASE_URL``). Tests pass
their own URL through ``config.attributes["database_url"]``.
"""

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine

from uaw.config import get_settings
from uaw.storage.models import Base

config = context.config
target_metadata = Base.metadata

# Only the command line configures logging; programmatic callers (tests) keep theirs.
if config.config_file_name is not None and "database_url" not in config.attributes:
    fileConfig(config.config_file_name)


def database_url() -> str:
    url = config.attributes.get("database_url")
    return str(url) if url else get_settings().database_url.get_secret_value()


def run_migrations_offline() -> None:
    """Print the SQL instead of running it (``alembic upgrade head --sql``)."""
    context.configure(
        url=database_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    engine = create_async_engine(database_url(), poolclass=pool.NullPool)
    async with engine.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_async_migrations())

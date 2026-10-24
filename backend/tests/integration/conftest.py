"""Fixtures for tests against a real PostgreSQL database (``docker compose up -d``).

The schema is created once per test session by running the Alembic migrations, so
the tests also prove that the migrations work. Each test starts from empty tables.
"""

import os
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import make_url, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from uaw.storage.db import create_session_factory

TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+asyncpg://uaw:uaw@127.0.0.1:5432/uaw_test"
)
BACKEND_DIR = Path(__file__).resolve().parents[2]


def alembic_config() -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.attributes["database_url"] = TEST_DATABASE_URL
    return config


@pytest.fixture(scope="session")
def database_url() -> str:
    # Tests truncate every table: refuse to run against a non-test database.
    database = make_url(TEST_DATABASE_URL).database or ""
    if not database.endswith("_test"):
        pytest.fail(f"TEST_DATABASE_URL must point to a *_test database, got '{database}'")
    try:
        command.upgrade(alembic_config(), "head")
    except OSError as exc:
        pytest.fail(f"PostgreSQL is unreachable ({exc}). Start it with: docker compose up -d")
    return TEST_DATABASE_URL


@pytest.fixture
async def session_factory(database_url: str) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_async_engine(database_url)
    async with engine.begin() as connection:
        # Clean before (not after) each test, so a failed test leaves its data to inspect.
        await connection.execute(
            text(
                "TRUNCATE repositories, ingestion_jobs, usage_records, budget_reservations CASCADE"
            )
        )
    yield create_session_factory(engine)
    await engine.dispose()


@pytest.fixture
async def session(
    session_factory: async_sessionmaker[AsyncSession],
) -> AsyncIterator[AsyncSession]:
    async with session_factory() as db_session:
        yield db_session

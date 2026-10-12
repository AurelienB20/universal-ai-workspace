"""Database engine and sessions (SQLAlchemy 2 asyncio API, asyncpg driver)."""

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from uaw.config import Settings


def create_engine(settings: Settings) -> AsyncEngine:
    """One engine per process: it owns the connection pool."""
    return create_async_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        # Detects connections closed by the server (restart, idle timeout) before use.
        pool_pre_ping=True,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    # Objects stay readable after commit instead of triggering a lazy reload,
    # which is not allowed with asyncio.
    return async_sessionmaker(engine, expire_on_commit=False)

"""Repositories that visitors of the public demo imported, each readable by its visitor
only. Like ``SnapshotStore``, it never commits.

Expiry is compared with the database clock (``now()``), the same clock that sets it.
"""

import uuid
from datetime import datetime, timedelta

from sqlalchemy import exists, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.storage.models import VisitorRepositoryRow


class VisitorAccessStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant(self, visitor_id: uuid.UUID, repository: str, ttl: timedelta) -> None:
        """Let ``visitor_id`` read ``repository`` ("owner/name", any case) for ``ttl``.

        Granting again extends the access; it never shortens it.
        """
        expires_at = func.now() + ttl
        stmt = insert(VisitorRepositoryRow).values(
            visitor_id=visitor_id, repository_key=repository.lower(), expires_at=expires_at
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[VisitorRepositoryRow.visitor_id, VisitorRepositoryRow.repository_key],
            set_={
                "expires_at": func.greatest(
                    VisitorRepositoryRow.expires_at, stmt.excluded.expires_at
                )
            },
        )
        await self._session.execute(stmt)

    async def repositories(self, visitor_id: uuid.UUID) -> dict[str, datetime]:
        """The repositories ``visitor_id`` may read now (lowercase "owner/name"), with
        the end of each access."""
        stmt = select(VisitorRepositoryRow.repository_key, VisitorRepositoryRow.expires_at).where(
            VisitorRepositoryRow.visitor_id == visitor_id,
            VisitorRepositoryRow.expires_at > func.now(),
        )
        return {row.repository_key: row.expires_at for row in await self._session.execute(stmt)}

    async def can_read(self, visitor_id: uuid.UUID, repository: str) -> bool:
        stmt = select(
            exists().where(
                VisitorRepositoryRow.visitor_id == visitor_id,
                VisitorRepositoryRow.repository_key == repository.lower(),
                VisitorRepositoryRow.expires_at > func.now(),
            )
        )
        return bool((await self._session.execute(stmt)).scalar_one())

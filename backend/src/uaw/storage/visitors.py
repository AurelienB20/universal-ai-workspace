"""Repositories that visitors of the public demo imported, each readable by its visitor
only. Like ``SnapshotStore``, it never commits.

Expiry is compared with the database clock (``now()``), the same clock that sets it.
"""

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, String, delete, exists, func, literal, or_, select, true
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.storage.models import IngestionJobRow, RepositoryRow, VisitorRepositoryRow


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

    async def extend_to(self, repository: str, new_name: str) -> None:
        """Give every visitor who may read ``repository`` the same access to
        ``new_name`` (the repository's name after a rename on GitHub)."""
        old_key, new_key = repository.lower(), new_name.lower()
        if old_key == new_key:
            return
        copies = select(
            VisitorRepositoryRow.visitor_id,
            literal(new_key, String(200)),
            VisitorRepositoryRow.expires_at,
        ).where(VisitorRepositoryRow.repository_key == old_key)
        stmt = insert(VisitorRepositoryRow).from_select(
            ["visitor_id", "repository_key", "expires_at"], copies
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

    async def delete_expired(self) -> int:
        """Delete the accesses that ended. Returns how many."""
        result = await self._session.execute(
            delete(VisitorRepositoryRow)
            .where(VisitorRepositoryRow.expires_at <= func.now())
            .returning(VisitorRepositoryRow.visitor_id)
        )
        return len(result.all())

    async def abandoned_repositories(self, keep: Collection[str]) -> list[str]:
        """Repositories that only visitors ever imported and that no visitor may read
        any more (lowercase "owner/name"), except those in ``keep``.

        A repository with no import job at all (imported before visitors existed, or
        by a script) is never returned.
        """
        stmt = select(RepositoryRow.key).where(
            RepositoryRow.key.not_in(keep) if keep else true(),
            _imports_of_repository(IngestionJobRow.visitor_id.is_not(None)),
            ~_imports_of_repository(IngestionJobRow.visitor_id.is_(None)),
            ~exists().where(VisitorRepositoryRow.repository_key == RepositoryRow.key),
        )
        return list((await self._session.scalars(stmt)).all())


def _imports_of_repository(condition: ColumnElement[bool]) -> ColumnElement[bool]:
    """Whether the repository has an import job matching ``condition``: asked for by
    its name, or by an older name GitHub redirected to it."""
    return exists().where(
        or_(
            IngestionJobRow.repository_key == RepositoryRow.key,
            func.lower(IngestionJobRow.repository) == RepositoryRow.key,
        ),
        condition,
    )

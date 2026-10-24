"""Persistence of token usage. Like ``SnapshotStore``, it never commits."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import delete, func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.storage.models import BudgetReservationRow, UsageRecordRow
from uaw.usage.meter import ModelUsage, Provider

Operation = Literal["import", "search", "ask"]


class UsageStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(
        self, operation: Operation, repository: str, usages: Sequence[ModelUsage]
    ) -> None:
        if not usages:
            return
        await self._session.execute(
            insert(UsageRecordRow),
            [
                {
                    "id": uuid.uuid4(),
                    "operation": operation,
                    "repository": repository,
                    "provider": usage.provider,
                    "model": usage.model,
                    "requests": usage.requests,
                    "input_tokens": usage.input_tokens,
                    "output_tokens": usage.output_tokens,
                }
                for usage in usages
            ],
        )

    async def tokens_since(self, provider: Provider, since: datetime) -> int:
        """Input + output tokens used with ``provider`` since ``since``."""
        stmt = select(
            func.coalesce(func.sum(UsageRecordRow.input_tokens + UsageRecordRow.output_tokens), 0)
        ).where(UsageRecordRow.provider == provider, UsageRecordRow.created_at >= since)
        return int((await self._session.execute(stmt)).scalar_one())

    async def lock_budget(self, provider: Provider) -> None:
        """Serialize budget checks for ``provider`` until the transaction ends, so that
        two requests cannot both check, then both reserve."""
        await self._session.execute(
            select(func.pg_advisory_xact_lock(func.hashtext(f"uaw.budget.{provider}")))
        )

    async def reserved_tokens(self, provider: Provider, now: datetime) -> int:
        """Tokens set aside by the operations in progress (unexpired reservations)."""
        stmt = select(func.coalesce(func.sum(BudgetReservationRow.tokens), 0)).where(
            BudgetReservationRow.provider == provider, BudgetReservationRow.expires_at > now
        )
        return int((await self._session.execute(stmt)).scalar_one())

    async def add_reservation(
        self, provider: Provider, tokens: int, expires_at: datetime
    ) -> uuid.UUID:
        reservation_id = uuid.uuid4()
        await self._session.execute(
            insert(BudgetReservationRow).values(
                id=reservation_id, provider=provider, tokens=tokens, expires_at=expires_at
            )
        )
        return reservation_id

    async def delete_reservations(
        self, ids: Sequence[uuid.UUID], *, expired_before: datetime
    ) -> None:
        """Delete the given reservations, and any that expired (left by a crash)."""
        await self._session.execute(
            delete(BudgetReservationRow).where(
                BudgetReservationRow.id.in_(ids)
                | (BudgetReservationRow.expires_at <= expired_before)
            )
        )

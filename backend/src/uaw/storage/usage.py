"""Persistence of token usage. Like ``SnapshotStore``, it never commits."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from sqlalchemy import func, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.storage.models import UsageRecordRow
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

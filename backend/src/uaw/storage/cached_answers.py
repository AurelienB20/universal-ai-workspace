"""Persistence of cached answers to suggested questions. Like ``SnapshotStore``, it
never commits."""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict
from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from uaw.generation.answerer import Answer
from uaw.storage.models import CachedAnswerRow, RepositoryRow, SnapshotRow

Language = Literal["fr", "en"]


class CachedAnswer(BaseModel):
    model_config = ConfigDict(frozen=True)

    question: str
    answer: Answer
    # When the model wrote the answer: shown to visitors, who must know it is not live.
    generated_at: datetime


class CachedAnswerStore:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def snapshot_id(self, repository: str, commit_sha: str) -> uuid.UUID | None:
        """The snapshot of ``repository`` ("owner/name", any case) at ``commit_sha``."""
        stmt = (
            select(SnapshotRow.id)
            .join(RepositoryRow, SnapshotRow.repository_id == RepositoryRow.id)
            .where(RepositoryRow.key == repository.lower(), SnapshotRow.commit_sha == commit_sha)
        )
        return await self._session.scalar(stmt)

    async def replace(
        self,
        snapshot_id: uuid.UUID,
        language: Language,
        answers: Sequence[tuple[str, Answer]],
    ) -> None:
        """Replace the suggestions of a snapshot in one language, in the given order."""
        await self._session.execute(
            delete(CachedAnswerRow).where(
                CachedAnswerRow.snapshot_id == snapshot_id, CachedAnswerRow.language == language
            )
        )
        if answers:
            await self._session.execute(
                insert(CachedAnswerRow),
                [
                    {
                        "id": uuid.uuid4(),
                        "snapshot_id": snapshot_id,
                        "language": language,
                        "position": position,
                        "question": _storable(question),
                        "answer": _storable(answer.model_dump(mode="json")),
                    }
                    for position, (question, answer) in enumerate(answers)
                ],
            )

    async def for_snapshot(self, snapshot_id: uuid.UUID, language: Language) -> list[CachedAnswer]:
        stmt = (
            select(CachedAnswerRow)
            .where(CachedAnswerRow.snapshot_id == snapshot_id, CachedAnswerRow.language == language)
            .order_by(CachedAnswerRow.position)
        )
        return [
            CachedAnswer(
                question=row.question,
                answer=Answer.model_validate(row.answer),
                generated_at=row.generated_at,
            )
            for row in (await self._session.scalars(stmt)).all()
        ]


# PostgreSQL text and JSONB cannot hold U+0000, which a model can write when quoting
# binary data (e.g. a b"\x00" separator). U+2400 is its visible stand-in.
_NUL, _NUL_SYMBOL = "\x00", "\u2400"


def _storable[T](value: T) -> T:
    """``value`` with every U+0000 in its strings replaced, at any depth."""
    if isinstance(value, str):
        return value.replace(_NUL, _NUL_SYMBOL)  # type: ignore[return-value]
    if isinstance(value, dict):
        return {key: _storable(item) for key, item in value.items()}  # type: ignore[return-value]
    if isinstance(value, list):
        return [_storable(item) for item in value]  # type: ignore[return-value]
    return value

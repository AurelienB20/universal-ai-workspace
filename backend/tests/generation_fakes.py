"""Test doubles for answer generation."""

import uuid
from collections.abc import AsyncIterator

from uaw.generation.claude import AnswerDelta, DraftAnswer, Generation, StreamEvent
from uaw.generation.prompt import Source, label_sources
from uaw.retrieval.retriever import SearchHit


def hit(path: str, start: int = 1, end: int = 3, content: str = "code\n") -> SearchHit:
    return SearchHit(
        chunk_id=uuid.uuid4(),
        path=path,
        language="python",
        start_line=start,
        end_line=end,
        section=None,
        content=content,
        score=0.5,
        url=f"https://github.com/o/r/blob/{'a' * 40}/{path}#L{start}-L{end}",
    )


def sources(*paths: str) -> list[Source]:
    return label_sources([hit(path) for path in paths])


class FakeAnswerModel:
    """Returns a fixed answer and records the prompts it received."""

    def __init__(self, answer: str, *, insufficient_context: bool = False) -> None:
        self.draft = DraftAnswer(answer=answer, insufficient_context=insufficient_context)
        self.calls: list[tuple[str, str]] = []

    async def generate(self, system: str, user_message: str) -> Generation:
        self.calls.append((system, user_message))
        return Generation(draft=self.draft, model="fake-model", input_tokens=100, output_tokens=20)

    async def stream(self, system: str, user_message: str) -> AsyncIterator[StreamEvent]:
        """The answer of ``generate``, in pieces of ``CHUNK_SIZE`` characters."""
        generation = await self.generate(system, user_message)
        text = generation.draft.answer
        for start in range(0, len(text), self.CHUNK_SIZE):
            yield AnswerDelta(text=text[start : start + self.CHUNK_SIZE])
        yield generation

    CHUNK_SIZE = 8

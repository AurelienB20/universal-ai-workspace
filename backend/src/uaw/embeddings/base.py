"""Provider-independent embedding interface and helpers."""

from collections.abc import Iterator, Sequence
from typing import Protocol

from uaw.domain.chunks import Chunk


class Embedder(Protocol):
    """Turns texts into vectors. Documents and queries are embedded differently."""

    @property
    def model(self) -> str: ...

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        """One vector per text, in input order."""
        ...

    async def embed_query(self, text: str) -> list[float]: ...


def embedding_text(chunk: Chunk) -> str:
    """The text that represents a chunk in vector space.

    The file path (and Markdown section) carries a lot of meaning for code search
    ("auth/middleware.py"), so it is prepended to the content. The stored chunk
    content stays untouched: citations are built from it.
    """
    header = f"File: {chunk.path}\n"
    if chunk.section:
        header += f"Section: {chunk.section}\n"
    return f"{header}\n{chunk.content}"


def batch_ranges(
    texts: Sequence[str], *, max_items: int, max_chars: int
) -> Iterator[tuple[int, int]]:
    """Split ``texts`` into consecutive ``[start, end)`` ranges within both limits.

    A single text longer than ``max_chars`` gets a batch of its own: the provider
    then decides (it rejects it, as truncation is disabled).
    """
    start, chars = 0, 0
    for index, text in enumerate(texts):
        if index > start and (index - start >= max_items or chars + len(text) > max_chars):
            yield start, index
            start, chars = index, 0
        chars += len(text)
    if start < len(texts):
        yield start, len(texts)

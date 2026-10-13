import random

import pytest

from uaw.domain.chunks import Chunk
from uaw.embeddings.base import batch_ranges, embedding_text


def chunk(section: str | None = None) -> Chunk:
    return Chunk(
        path="src/auth.py",
        language="python",
        start_line=3,
        end_line=4,
        content="def login():\n    ...\n",
        section=section,
    )


def test_embedding_text_starts_with_the_file_path() -> None:
    assert embedding_text(chunk()) == "File: src/auth.py\n\ndef login():\n    ...\n"


def test_embedding_text_includes_the_markdown_section() -> None:
    assert embedding_text(chunk("Install > Windows")).startswith(
        "File: src/auth.py\nSection: Install > Windows\n\n"
    )


@pytest.mark.parametrize(
    ("lengths", "max_items", "max_chars", "expected"),
    [
        ([], 3, 100, []),
        ([10, 10, 10, 10], 3, 100, [(0, 3), (3, 4)]),
        ([60, 30, 20, 50], 10, 100, [(0, 2), (2, 4)]),
        ([10, 500, 10], 10, 100, [(0, 1), (1, 2), (2, 3)]),  # oversized text alone
        ([100, 100], 10, 100, [(0, 1), (1, 2)]),
    ],
)
def test_batch_ranges(
    lengths: list[int], max_items: int, max_chars: int, expected: list[tuple[int, int]]
) -> None:
    texts = ["x" * n for n in lengths]

    assert list(batch_ranges(texts, max_items=max_items, max_chars=max_chars)) == expected


def test_batch_ranges_cover_every_text_once_within_limits() -> None:
    rng = random.Random(42)
    for _ in range(200):
        texts = ["x" * rng.randint(1, 80) for _ in range(rng.randint(0, 50))]
        max_items, max_chars = rng.randint(1, 10), rng.randint(50, 300)

        ranges = list(batch_ranges(texts, max_items=max_items, max_chars=max_chars))

        assert [i for start, end in ranges for i in range(start, end)] == list(range(len(texts)))
        for start, end in ranges:
            assert 0 < end - start <= max_items
            assert sum(map(len, texts[start:end])) <= max_chars or end - start == 1

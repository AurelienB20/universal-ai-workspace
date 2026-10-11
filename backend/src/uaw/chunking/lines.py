"""Line splitting and the generic line-window chunking algorithm.

All chunkers work on lines and line ranges, never on character offsets, so every
chunk maps to an exact, citable line range.
"""

from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkingConfig:
    max_chars: int = 2000  # ~500 tokens at ~4 characters per token
    min_chars: int = 400  # small blocks are grouped until they reach this size
    overlap_lines: int = 2  # context carried over when a cut happens mid-block

    def __post_init__(self) -> None:
        if not 0 < self.min_chars < self.max_chars:
            raise ValueError("chunking requires 0 < min_chars < max_chars")
        if self.overlap_lines < 0:
            raise ValueError("overlap_lines must be >= 0")


def split_lines(text: str) -> list[str]:
    """Split text into lines, keeping line endings, using ``\\n`` as the only separator.

    ``str.splitlines()`` also splits on characters such as form feed (``\\x0c``) or
    ``\\u2028``. GitHub does not, so using it would shift line numbers and break
    citations.
    """
    lines = text.split("\n")
    result = [line + "\n" for line in lines[:-1]]
    if lines[-1]:
        result.append(lines[-1])
    return result


def is_blank(line: str) -> bool:
    return not line.strip()


def window_ranges(
    lines: Sequence[str],
    scores: Sequence[int],
    config: ChunkingConfig,
) -> list[tuple[int, int]]:
    """Group lines into ranges ``[start, end)`` of at most ``config.max_chars``.

    ``scores[i]`` rates cutting *before* line ``i``: 0 means never cut here unless
    forced, 3 means a new top-level block starts here. The algorithm is greedy:

    - a range is closed early at a score-3 boundary once it holds ``min_chars``;
    - when the next line would exceed ``max_chars``, the range is cut at the best
      boundary seen (the latest one among ties). Boundaries count once the range
      holds ``min_chars``, except score-3 ones which always count;
    - without any boundary, it is cut right there and the next range starts
      ``overlap_lines`` earlier to keep some context.

    A single line longer than ``max_chars`` becomes its own range: content is never
    altered, so the line-range invariant always holds.

    Leading and trailing blank lines are trimmed from each range; blank-only ranges
    are dropped.
    """
    if len(scores) != len(lines):
        raise ValueError("scores and lines must have the same length")

    ranges: list[tuple[int, int]] = []
    start = 0
    while start < len(lines):
        end, size = start, 0
        best_cut, best_score = -1, -1
        forced = False
        while end < len(lines):
            if end > start and size >= config.min_chars and scores[end] >= 3:
                break  # natural end of a block, and the range is big enough
            if end > start and size + len(lines[end]) > config.max_chars:
                forced = True
                break
            size += len(lines[end])
            end += 1
            # Cut candidates: any boundary once the range is big enough, and top-level
            # boundaries always (a small chunk beats a definition split in two).
            if (
                end < len(lines)
                and (size >= config.min_chars or scores[end] >= 3)
                and scores[end] >= best_score
            ):
                best_cut, best_score = end, scores[end]

        trimmed = None
        overlap = 0
        if forced and best_score > 0:
            # Cut imposed by the size limit: fall back to the best boundary seen.
            end = best_cut
            trimmed = _trim_blank_lines(lines, start, end)
        elif forced:
            # No boundary at all: cut mid-block, with some overlap for context.
            trimmed = _trim_blank_lines(lines, start, end)
            first_line = trimmed[0] if trimmed else start
            overlap = _fitting_overlap(lines, first_line, end, config)
        else:
            trimmed = _trim_blank_lines(lines, start, end)

        # Never emit a range contained in the previous one (possible with overlap).
        if trimmed is not None and (not ranges or trimmed[1] > ranges[-1][1]):
            ranges.append(trimmed)
        start = end - overlap if end < len(lines) else end
    return ranges


def _fitting_overlap(
    lines: Sequence[str], first_line: int, end: int, config: ChunkingConfig
) -> int:
    """Largest overlap (up to ``config.overlap_lines``) that keeps the next range useful.

    The next range must start after the current range's first line, and the overlap
    plus line ``end`` must fit in ``max_chars`` so the next range contains new lines.
    """
    for overlap in range(config.overlap_lines, 0, -1):
        next_start = end - overlap
        if next_start > first_line and (
            sum(len(line) for line in lines[next_start : end + 1]) <= config.max_chars
        ):
            return overlap
    return 0


def _trim_blank_lines(lines: Sequence[str], start: int, end: int) -> tuple[int, int] | None:
    while start < end and is_blank(lines[start]):
        start += 1
    while end > start and is_blank(lines[end - 1]):
        end -= 1
    return (start, end) if start < end else None

"""Markdown chunking: one section per heading, split further when too long.

Only ATX headings (``# Title``) are recognized; setext headings (underlined with
``===``) are treated as text. Headings inside fenced code blocks are ignored.
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass

from uaw.chunking.lines import ChunkingConfig, is_blank, window_ranges

# ATX headings (CommonMark): up to 3 spaces, 1-6 '#', then a space or end of line.
_HEADING_RE = re.compile(r" {0,3}(#{1,6})(?:[ \t]+(.*?))?[ \t#]*")
_FENCE_RE = re.compile(r" {0,3}(`{3,}|~{3,})")


@dataclass(frozen=True)
class Span:
    start: int  # 0-based, inclusive
    end: int  # 0-based, exclusive
    section: str | None


def markdown_spans(lines: Sequence[str], config: ChunkingConfig) -> list[Span]:
    spans: list[Span] = []
    for start, end, section in _sections(lines):
        section_lines = lines[start:end]
        scores = _paragraph_scores_outside_fences(section_lines)
        for sub_start, sub_end in window_ranges(section_lines, scores, config):
            spans.append(Span(start + sub_start, start + sub_end, section))
    return spans


def _sections(lines: Sequence[str]) -> list[tuple[int, int, str | None]]:
    """Split at headings, ignoring '#' lines inside fenced code blocks."""
    sections: list[tuple[int, int, str | None]] = []
    stack: list[tuple[int, str]] = []  # (level, title) of the enclosing headings
    current_start, current_section = 0, None
    for i, (heading, in_fence) in enumerate(_scan(lines)):
        if heading is None or in_fence:
            continue
        level, title = heading
        if i > current_start:
            sections.append((current_start, i, current_section))
        while stack and stack[-1][0] >= level:
            stack.pop()
        stack.append((level, title))
        current_start = i
        current_section = " > ".join(t for _, t in stack if t) or None
    if current_start < len(lines):
        sections.append((current_start, len(lines), current_section))
    return sections


def _paragraph_scores_outside_fences(lines: Sequence[str]) -> list[int]:
    scores = [0] * len(lines)
    for i, (_, in_fence) in enumerate(_scan(lines)):
        if i > 0 and not in_fence and is_blank(lines[i - 1]) and not is_blank(lines[i]):
            scores[i] = 2
    return scores


def _scan(lines: Sequence[str]) -> list[tuple[tuple[int, str] | None, bool]]:
    """For each line: its (level, title) if it is a heading, and whether it is in a fence.

    Fence delimiter lines count as inside the fence.
    """
    result: list[tuple[tuple[int, str] | None, bool]] = []
    fence: str | None = None
    for line in lines:
        text = line.rstrip("\r\n")
        fence_match = _FENCE_RE.match(text)
        if fence is None and fence_match:
            fence = fence_match.group(1)
            result.append((None, True))
            continue
        if fence is not None:
            if text.strip().startswith(fence[0] * len(fence)) and not text.strip().strip(fence[0]):
                fence = None
            result.append((None, True))
            continue
        heading_match = _HEADING_RE.fullmatch(text)
        if heading_match:
            title = (heading_match.group(2) or "").strip()
            result.append(((len(heading_match.group(1)), title), False))
        else:
            result.append((None, False))
    return result

"""Boundary scores: how good a place is it to cut *before* each line?

Scores feed ``window_ranges``:
    3  a top-level definition starts here (with its decorators/comments)
    2  a top-level line follows a blank line (paragraph or block separator)
    1  an indented line follows a blank line (separator inside a block)
    0  anywhere else

This is a language-agnostic heuristic, not a parser. It recognizes definitions in
the most common languages (Python, JS/TS, Go, Rust, Java/Kotlin, C#, Ruby, PHP…).
AST-based chunking (e.g. tree-sitter) is a planned, measured improvement.
"""

import re
from collections.abc import Sequence

from uaw.chunking.lines import is_blank

_MODIFIERS = (
    r"(?:(?:export|default|public|private|protected|internal|static|abstract|final|"
    r"sealed|async|unsafe|pub(?:\([^)]*\))?)\s+)*"
)
_DEFINITION_RE = re.compile(
    _MODIFIERS + r"(?:def|class|function|func|fn|impl|struct|enum|trait|interface|type|"
    r"module|namespace|object|const|let|var)\b"
)
# Lines that belong to the definition right below them: decorators, annotations,
# doc comments.
_ATTACHED_PREFIXES = ("@", "#[", "#", "//", "/*", "*")


def paragraph_scores(lines: Sequence[str]) -> list[int]:
    scores = [0] * len(lines)
    for i in range(1, len(lines)):
        if is_blank(lines[i]) or not is_blank(lines[i - 1]):
            continue
        scores[i] = 1 if lines[i][0].isspace() else 2
    return scores


def code_scores(lines: Sequence[str]) -> list[int]:
    """Paragraph scores, raised at definitions.

    Top-level definitions score 3. Indented ones (methods) score 2 when a blank line
    precedes them, so long classes are preferably split between methods.
    """
    scores = paragraph_scores(lines)
    for i, line in enumerate(lines):
        if not _DEFINITION_RE.match(line.lstrip()):
            continue
        start = i
        while start > 0 and _is_attached(lines[start - 1]):
            start -= 1
        top_level = not line[:1].isspace()
        if top_level:
            scores[start] = 3
        elif start > 0 and is_blank(lines[start - 1]):
            scores[start] = max(scores[start], 2)
        else:
            continue
        for k in range(start + 1, i + 1):
            scores[k] = 0  # never separate a definition from its decorators/comments
    return scores


def _is_attached(line: str) -> bool:
    stripped = line.lstrip()
    return bool(stripped) and stripped.startswith(_ATTACHED_PREFIXES)

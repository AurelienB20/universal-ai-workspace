# ADR 0001: Chunks are exact line ranges, cut at detected boundaries

- **Status:** accepted
- **Date:** 2026-10-11

## Context

Every answer cites lines of a file, and each citation links to those lines on GitHub. A
chunk is therefore the unit a citation can point to: if a chunk does not map exactly to a
line range, a citation cannot be exact either. Chunks also need to be coherent (a whole
function rather than half of two) for retrieval to work well.

## Decision

A chunk's content is exactly lines `start_line` to `end_line` of its file, at most about
2,000 characters. A greedy line window is driven by boundary scores: top-level
definitions (kept with their decorators and doc comments), then methods, then blank
lines. Markdown is split by heading, ignoring headings inside code fences, and each chunk
keeps its heading breadcrumb. Lines are split on `\n` only, as GitHub does, so line
numbers stay aligned even in files with form feeds or Unicode line separators.

## Alternatives considered

- **Fixed-size token windows.** Simple, but they cut through functions, and a chunk would
  no longer be a clean line range.
- **A syntax-tree parser per language (tree-sitter).** Precise, but one grammar per
  language to install and maintain, for a small gain over top-level boundaries.

## Consequences

- Citations are exact by construction. An invariant test checks, on every chunk and on 50
  randomly generated documents, that the content is exactly its line range.
- The boundary heuristics are language-agnostic: decent everywhere, perfect nowhere.
- A forced cut inside a long block without boundaries gets a small overlap.

## Revisit when

Retrieval evaluation shows chunk boundaries are a main source of misses for one language;
a parser could then be added for that language only.

## Evidence

[`chunking/lines.py`](../../backend/src/uaw/chunking/lines.py),
[`chunking/markdown.py`](../../backend/src/uaw/chunking/markdown.py),
[tests](../../backend/tests/unit/test_chunking.py)

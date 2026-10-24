# ADR 0011: Test files rank lower; hybrid search is measured, and left off

- **Status:** accepted
- **Date:** 2026-10-24

## Context

The line-level evaluation (ADR 0005) showed that questions about a name (`What does
PROPAGATE_EXCEPTIONS change?`) found the right passage, but rarely first: test files,
which repeat names, ranked above the code that defines them. Hybrid search (full text
alongside vectors) is the usual answer to exact-name queries, so it was built and measured.

## Decision

- **Rank test files lower:** in the final ranking, chunks from test files (a `tests/`
  directory, `test_*.py`, `*_test.py`) have their score multiplied by 0.5
  (`RETRIEVAL_TEST_WEIGHT`), unless the question mentions tests.
- **Keep hybrid search available but off** (`RETRIEVAL_MODE=vector`). It is implemented: a
  `tsvector` column with a GIN index (migration 0006), the `simple` configuration so that
  code words are kept, joined forms of snake_case names, and Reciprocal Rank Fusion with
  the vector ranking.

## Alternatives considered

- **Hybrid search on every word of the question:** worse on the dev split (Flask MRR 0.738
  → 0.503). Common words match file names and long passages, and `ts_rank` ignores word
  rarity.
- **Hybrid search on the question's code names only:** worse alone (0.663), and no change
  once tests rank lower: the passages containing a name are mostly tests.
- **Excluding tests entirely:** would lose questions that are about tests.

## Consequences

- Flask, test split (never used for tuning): MRR 0.68 → 0.76, exact-name questions 0.80 →
  1.00, no question worse. itsdangerous: 0.88 → 0.92.
- A heuristic on file paths: a project that keeps its tests elsewhere gets no benefit.
- Every import also computes the full-text vectors (one SQL statement), for a mode that is
  off. The cost is small, and it keeps the option measurable.

## Revisit when

A full-text ranking that knows word rarity is available (BM25, e.g. a PostgreSQL extension),
or a reranker is added: both could make the text signal useful, and both are measured the
same way.

## Evidence

[`retrieval/retriever.py`](../../backend/src/uaw/retrieval/retriever.py),
[`storage/fulltext.py`](../../backend/src/uaw/storage/fulltext.py),
[measurements](../../backend/eval/results/README.md),
[tests](../../backend/tests/integration/test_hybrid_search.py)

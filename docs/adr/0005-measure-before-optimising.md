# ADR 0005: Retrieval changes are kept only if a measured evaluation improves

- **Status:** accepted
- **Date:** 2026-10-13

## Context

RAG has many well-known improvements: hybrid search (full text and vectors), rerankers,
query rewriting, other chunk sizes. Each adds cost or latency, and each can also lower
quality on a given corpus. Without measurement there is no way to tell.

## Decision

Retrieval is measured on a labeled question set before and after any change: hit@k,
recall@k (file level) and MRR. A change is kept only if it measurably helps. The
evaluation command checks that every labeled file is indexed, so a stale label cannot
silently count as a miss.

## Alternatives considered

- **Adding the usual techniques up front.** Quick to justify, impossible to verify.
- **Judging answers by reading them.** Useful for spotting problems, not for comparing two
  configurations.

## Consequences

- The first set (20 questions on `pallets/itsdangerous`, file-level labels) scored hit@1
  1.00 and MRR 1.00: saturated, it could not show any improvement. It was replaced
  (2026-10-24) by 65 questions over itsdangerous and Flask, labeled with line ranges,
  categorised (lookup, paraphrase, identifier, multi-file, cross-lingual, unanswerable) and
  split into dev and test. On Flask, vector search alone scores hit@1 0.63 and MRR 0.71 at
  line level, from 0.91 (`lookup`) down to 0.44 (`cross-lingual`): there is now room to
  measure a change. See [the analysis](../../backend/eval/results/README.md).
- Changes are compared on the dev split; the test split is run once per finished change.
- Retrieval is evaluated without the LLM, so a run costs one embedding call per question.

## Revisit when

Never as a rule. The metrics may change (answer-level evaluation, for example).

## Evidence

[`evaluation/metrics.py`](../../backend/src/uaw/evaluation/metrics.py),
[`eval/itsdangerous.json`](../../backend/eval/itsdangerous.json)

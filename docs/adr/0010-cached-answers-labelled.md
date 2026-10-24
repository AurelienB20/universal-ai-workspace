# ADR 0010: Suggested questions are answered once and served from a labelled cache

- **Status:** accepted
- **Date:** 2026-10-24

## Context

A visitor to the demo should see an answer at once, without waiting 10 seconds or costing
anything. Serving a stored answer as if it were live would be misleading, and an answer
must never describe code other than the indexed commit.

## Decision

An admin call (`PUT /repositories/{owner}/{name}/suggestions`) answers up to six
questions through exactly the same path as a live question (budget reservation,
concurrency limit, usage recording) and stores the answers with their trace, all or
nothing. `GET` serves them to any allowed key without a model call. The interface shows
each one with "Cached answer, generated on …", its model and its commit. Cached answers
belong to a snapshot and are deleted with it.

## Alternatives considered

- **Caching every live answer by question text.** More hits, but visitors' questions
  rarely repeat word for word, and stale answers would need invalidation rules.
- **Static answers written in the frontend.** Free, but no longer real model output with
  verified citations.

## Consequences

- An instant, free first impression, honestly labelled.
- After a new import, a repository has no suggestions until they are generated again.
- PostgreSQL refuses U+0000 in text and JSONB; a model quoting binary data can write one,
  so it is replaced by U+2400 before storage.

## Revisit when

Visitors' questions do repeat: a semantic cache keyed by question embeddings, with the
same labelling.

## Evidence

[`storage/cached_answers.py`](../../backend/src/uaw/storage/cached_answers.py),
[`api/repositories.py`](../../backend/src/uaw/api/repositories.py),
[tests](../../backend/tests/integration/test_suggestions.py)

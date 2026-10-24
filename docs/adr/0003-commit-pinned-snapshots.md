# ADR 0003: Each import is an immutable snapshot pinned to one commit

- **Status:** accepted
- **Date:** 2026-10-13

## Context

A citation links to lines of a file. If the repository changes after indexing, a link to
`main` would point to different lines than the ones the model read. An import also takes
time (download, chunking, embeddings), and a half-built index must never be searched.

## Decision

An import pins the latest commit SHA of the default branch and creates a snapshot for it.
The snapshot stays `indexing` until every chunk has its vector, then becomes `ready`;
searches only use the latest ready snapshot. Citations link to the pinned commit.
Re-importing an already indexed commit reuses its snapshot without any API call. After a
new snapshot is ready, older ones are deleted in the same transaction, keeping the two
most recent so that a question still reading the previous one is not cut short.

## Alternatives considered

- **Updating chunks in place.** Cheaper, but a citation could point to lines that changed,
  and a failed update would leave a mixed index.
- **Keeping every snapshot.** Simple, but storage grows with every import.

## Consequences

- A citation always shows the lines that were really read, even after new commits.
- An index is never searched half-built; a failed import deletes its partial snapshot.
- The repository is not up to date until it is imported again.

## Revisit when

A repository must be followed continuously: incremental imports triggered by a webhook,
reusing unchanged files' chunks (the `content_sha256` column already allows it).

## Evidence

[`ingestion/pipeline.py`](../../backend/src/uaw/ingestion/pipeline.py),
[`storage/store.py`](../../backend/src/uaw/storage/store.py),
[tests](../../backend/tests/integration/test_ingestion.py)

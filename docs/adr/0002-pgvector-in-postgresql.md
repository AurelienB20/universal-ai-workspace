# ADR 0002: Vectors live in PostgreSQL with pgvector, not in a vector database

- **Status:** accepted
- **Date:** 2026-10-12

## Context

The system stores repositories, snapshots, documents, chunks, import jobs and token
usage, all relational, plus one 1,024-dimension vector per chunk. The target deployment is
one small server, run by one person.

## Decision

Use PostgreSQL 16 with pgvector: vectors are a column of the `chunks` table, indexed with
HNSW for cosine distance. Integrity is enforced by the database itself (commit SHA format,
unique paths per snapshot, valid line ranges, a composite foreign key keeping a chunk and
its document in the same snapshot).

## Alternatives considered

- **A dedicated vector database (Qdrant, Weaviate, Pinecone).** More vector features, but
  one more service to run and back up, and no transaction shared with the metadata: an
  import could leave vectors without chunks, or the reverse.
- **An in-process index (FAISS).** Fast, but not persistent or transactional on its own.

## Consequences

- An import is saved entirely or not at all, in one database.
- One backup covers everything.
- Filtered search needs care: one HNSW index covers every repository, so a plain filtered
  query keeps the nearest chunks of the whole table, then filters them all out. pgvector's
  iterative index scans fix it; an integration test forces the index plan and shows the
  plain query losing every result.
- Hand-written test vectors that are all equidistant build a degenerate HNSW graph; the
  tests use random vectors instead.

## Revisit when

Tens of millions of vectors, or multi-tenant search at a scale where a dedicated engine's
sharding and filtering pay for the extra service.

## Evidence

[`storage/models.py`](../../backend/src/uaw/storage/models.py),
[`storage/search.py`](../../backend/src/uaw/storage/search.py),
[filtered search test](../../backend/tests/integration/test_search.py)

# Architecture decision records

Short records of the decisions that shape this project: the context, what was decided,
the alternatives ruled out, what it costs, and what would make us change it. They are
kept in the order the decisions were made.

| # | Decision | Date |
|---|---|---|
| [0001](0001-line-addressed-chunking.md) | Chunks are exact line ranges, cut at detected boundaries | 2026-10-11 |
| [0002](0002-pgvector-in-postgresql.md) | Vectors live in PostgreSQL with pgvector, not in a vector database | 2026-10-12 |
| [0003](0003-commit-pinned-snapshots.md) | Each import is an immutable snapshot pinned to one commit | 2026-10-13 |
| [0004](0004-no-queue-or-redis-yet.md) | No task queue or Redis yet: imports run in the API process | 2026-10-13 |
| [0005](0005-measure-before-optimising.md) | Retrieval changes are kept only if a measured evaluation improves | 2026-10-13 |
| [0006](0006-server-resolved-citations.md) | The model cites opaque IDs; the server resolves them | 2026-10-23 |
| [0007](0007-anthropic-sdk-without-framework.md) | The Anthropic SDK directly, with structured output, no RAG framework | 2026-10-23 |
| [0008](0008-nextjs-server-as-proxy.md) | The browser talks to the Next.js server, which holds the API key | 2026-10-24 |
| [0009](0009-budget-reservations.md) | Daily budgets are reserved atomically, under a PostgreSQL lock | 2026-10-24 |
| [0010](0010-cached-answers-labelled.md) | Suggested questions are answered once and served from a labelled cache | 2026-10-24 |

The *How it is built* page of the web interface presents the same decisions in a shorter
form, in French and English.

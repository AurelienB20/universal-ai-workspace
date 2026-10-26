# ADR 0014: Visitors import their own repository, privately, under a cost cap, for a day

- **Status:** accepted
- **Date:** 2026-10-26

## Context

The public demo only answered questions about repositories the admin had imported. Trying
the tool on one's own code is far more convincing, but opening imports to anyone raises
four problems: cost (embeddings are paid for), abuse (one visitor importing a hundred
repositories, or one very large one), hostile content (a repository written to steer the
model's answers, then shown to other visitors) and disk space on a 40 GB server.

## Decision

With `PUBLIC_IMPORTS_ENABLED=true`, a visitor can import a public GitHub repository:

- **Private.** The web server gives each visitor a random identifier in an HttpOnly
  cookie and sends it as `X-Visitor-Id`, trusted only with the demo key. A
  `visitor_repositories` row grants that visitor, and nobody else, access to the
  repository. Anyone else gets the same 404 as for a repository never imported.
- **Temporary.** The access lasts `VISITOR_ACCESS_HOURS` (24). A task in the API process
  deletes ended accesses every hour, then the repositories that only visitors imported and
  nobody may read any more. The demo's repositories, the admin's, and any repository with
  no import job are never deleted.
- **Capped before spending.** Visitor imports are limited to 20 MB and 300 files, and
  their embedding cost is estimated after chunking, before any token is spent: 3
  characters per token (measured on the server: 4.2 on Flask, 3.9 on itsdangerous, so
  the estimate is high). Above `VISITOR_MAX_IMPORT_TOKENS` (400,000), the import fails
  with a clear message.
- **Quotas.** 2 imports per visitor and 20 in total per UTC day, counted in the database
  under an advisory lock; 3 per address per day, in memory; one visitor import at a time,
  in its own lane beside the admin's, with at most 3 waiting. 15 questions per visitor
  and per day about their own repositories.
- **A repository already indexed is shared, not imported again.** The visitor gets access
  at once, for free, and does not use a quota. This also keeps a visitor import, cut down
  to 300 files, from replacing a complete snapshot the admin imported.

## Alternatives considered

- **A separate embedding budget for visitors** (a new usage category and counter). The
  quotas already bound what visitors can spend: at most 20 × 400,000 = 8 million tokens
  a day. The settings instead refuse an embedding budget that would not leave room for
  questions after that. Same protection, nothing new to count.
- **Visitor repositories visible to everyone.** Simpler, but anyone could then plant
  content that steers the answers other visitors read.
- **Accounts, or a CAPTCHA.** More friction for a recruiter trying the demo. Kept for
  later if the quotas are not enough.
- **A queue service (Redis, Celery).** Not needed for one import at a time (see ADR 0004).

## Consequences

- Worst case, visitors cost about 8 million embedding tokens a day (about 1.4 USD with
  voyage-code-3). On the server, `DAILY_EMBEDDING_TOKEN_BUDGET` goes from 5 to 13 million.
- The cookie proves nothing: a script can drop it at will. The per-address and global
  quotas are what protect; the cookie only keeps visitors apart.
- The per-address and question counts are lost on a restart: an accepted gap, as the
  database counts bound the total anyway.
- A visitor cannot refresh a repository someone already indexed: it is shared as it is,
  and goes away with the last access.

## Revisit when

User accounts arrive (multi-user): access is tied to the account rather than a cookie, and
quotas become per account.

## Evidence

[`api/imports.py`](../../backend/src/uaw/api/imports.py),
[`storage/visitors.py`](../../backend/src/uaw/storage/visitors.py),
[`maintenance.py`](../../backend/src/uaw/maintenance.py),
[public import tests](../../backend/tests/integration/test_public_imports.py),
[cleanup tests](../../backend/tests/integration/test_visitor_cleanup.py)

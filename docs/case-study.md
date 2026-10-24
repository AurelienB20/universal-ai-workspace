# Case study: Universal AI Workspace

*Asking questions about a code base, with answers that can be checked line by line.*

Built by Aurélien Benoit, October 11 to 24, 2026, in small milestones, each tested and
reviewed before the next.

## TL;DR

- **What it is:** a retrieval-augmented generation (RAG) system for GitHub repositories.
  Import a repository, ask a question, get an answer whose citations link to the exact
  lines at the indexed commit. Under each answer, the evidence: the passages the model
  read, their scores, and which ones it cited.
- **What makes it hard:** citations that cannot be invented, repositories treated as
  hostile input, a public demo that strangers cannot abuse or turn into a bill, and the
  discipline to measure before optimising.
- **Results:** about 10 s and $0.03 per answer, 460 backend and 32 frontend tests, every
  check in CI, and eight problems found by tests, an audit or by using the real system,
  described below.

## The problem

Understanding an unfamiliar code base is slow: search finds keywords, not intent, and a
chatbot answers fluently but cannot be trusted on details. An answer about code is only
useful if it can be checked quickly, so the goal was not "an LLM that knows the code" but
**an answer where every claim points to the lines it comes from**, and where a wrong
citation is impossible rather than unlikely.

## Constraints

- **A small budget.** Paid models (Voyage embeddings, Claude answers), a small server, and
  a public demo that anyone can open: the cost had to be bounded by design.
- **A modest machine.** Development on an 8 GB Windows laptop where Docker Desktop does not
  fit: PostgreSQL runs in WSL, and Docker images are built and checked by CI only.
- **Explainability.** Every component had to be understandable and defensible in an
  interview: no framework hiding the prompt, no infrastructure without a reason.

## Architecture

Two phases. **At import**, the repository is fetched at a pinned commit, read safely,
split into line-addressed passages and embedded into PostgreSQL + pgvector. **At each
question**, the question is embedded, the nearest passages of the latest snapshot are
retrieved, Claude answers from them only, and the server resolves the citations.

```
Browser ──► Next.js (holds the API key, CSP) ──► FastAPI (roles, rate limits, budgets)
                                                   ├──► PostgreSQL + pgvector
                                                   ├──► Voyage (embeddings)
                                                   ├──► Claude (answers)
                                                   └──► GitHub (commit archive)
```

The decisions behind it are recorded as [architecture decision records](adr/README.md);
the most important ones:

| Decision | Why | Cost accepted |
|---|---|---|
| [Server-resolved citations](adr/0006-server-resolved-citations.md) | Invented sources become impossible, not just unlikely | A citation covers a whole passage |
| [Line-addressed chunks](adr/0001-line-addressed-chunking.md) | A citation can only be exact if a chunk is an exact line range | Heuristic boundaries, not a parser |
| [Commit-pinned snapshots](adr/0003-commit-pinned-snapshots.md) | Citations show the lines that were really read | Re-import to update |
| [pgvector in PostgreSQL](adr/0002-pgvector-in-postgresql.md) | One transactional store, one backup | Filtered search needs care |
| [Budgets by reservation](adr/0009-budget-reservations.md) | A hard ceiling, even under concurrency | Budget under-used by the margin |
| [No queue or Redis yet](adr/0004-no-queue-or-redis-yet.md) | Two fewer services for a one-server demo | A single API process |

## What went wrong, and what changed

The most useful part of the project. Each of these was found by a test, an audit or by
using the real system, and each fix is covered by a test.

1. **The daily budget did not hold under concurrency.** The first version checked "spent
   today < budget" before each question, but usage is only recorded once the answer is
   done, about 10 s later. Twenty simultaneous questions would all pass. Each question now
   reserves its worst-case cost under a PostgreSQL advisory lock. To make sure the test
   proves something, I removed the lock and ran it again: it failed three times out of
   three.

2. **Filtered vector search could return nothing.** With one HNSW index over every
   repository, the index returns the nearest chunks of the whole table, then the
   repository filter removes them. On a small repository among large ones, every result
   disappears. pgvector's iterative scans fix it; an integration test forces the index
   plan and shows the plain query losing every result.

3. **A test passed or failed at random.** Two snapshots created in one transaction got the
   same `created_at` (PostgreSQL's `now()` is the transaction start), so "the latest" was
   decided by a random UUID. The test now creates them in separate transactions, as real
   imports do. A related lesson: hand-written, equidistant test vectors build a degenerate
   HNSW graph, so tests use random vectors.

4. **Caching answers failed on accents.** Testing the demo by hand, generating the
   suggested answers returned a 500. My first diagnosis (a NUL character in the answer) was
   wrong; the error message said `SQL_ASCII`: the local PostgreSQL cluster had been created
   with the C locale, where JSONB refuses non-ASCII text, and French answers have accents.
   Production images were not affected. The setup script now creates UTF-8 databases, and
   the integration tests refuse to run on anything else. The NUL case turned out to be
   real too (PostgreSQL refuses U+0000 even in UTF-8), so it is handled as well.

5. **A browser's automatic translation broke the demo.** While recording the screenshots,
   Chrome translated the English page into French and turned `pallets/itsdangerous` into
   "palettes/c'est dangereux". The page is now marked `translate="no"`: it has its own
   French and English versions.

6. **The evidence view was misleading.** The first similarity bars were scaled to the best
   passage. On a real question, the eight scores were between 0.49 and 0.50, so every bar
   looked full and "perfect". They now show the raw cosine similarity on a fixed 0-1 scale.

7. **One answer could cost $0.34.** The output cap was 16,000 tokens while the longest
   measured answer used about 900. It is now 2,000, which bounds the worst case.

8. **The evaluation stopped being informative.** The 20-question set scores hit@1 1.00 and
   MRR 1.00. Rather than claiming a perfect system, the conclusion is that this set is too
   easy to measure anything; a harder one comes before any retrieval change.

## Measurements

On `pallets/itsdangerous` (41 files, 99 passages), with Claude Opus 5.5 at effort
`medium`:

| | |
|---|---|
| Answer time | about 10 s (7 to 12 s observed): ~1 s retrieval, ~8 s generation |
| Tokens per question | 1,800 to 5,800 in, 400 to 900 out |
| Cost per question | about $0.03; every model call is metered and stored |
| Retrieval (20 labeled questions) | hit@1 1.00, recall@5 0.96, MRR 1.00 (saturated) |
| Tests | 460 backend (unit and PostgreSQL integration), 32 frontend; CI on every push |

## What I would do next

1. **A harder evaluation set**, with questions spanning several files and questions with
   no answer, then **hybrid search** (PostgreSQL full text with vectors, fused with RRF)
   and a **reranker**, each kept only if it improves the numbers.
2. **Streaming answers** (server-sent events): sources first, then the text, then the
   server-validated citations.
3. **A public deployment** on one server: Docker Compose, Caddy for HTTPS, images built by
   CI, and backups that are restored in a test, not just taken.
4. **More sources and users**: PostgreSQL databases and PDFs as sources, then workspaces
   with per-user budgets (the reservation mechanism already supports a key per tenant).

## What I learned

- **Guarantees beat instructions.** "Do not invent citations" in a prompt reduces the
  problem; resolving IDs on the server removes it. The same goes for budgets: a lock, not
  a check.
- **A test should be able to fail.** Breaking the code on purpose (removing the lock) is
  the quickest way to know a test is worth something.
- **Look at the real system.** Three of the eight problems above (encoding, translation,
  misleading bars) passed every test and were obvious within minutes of using the real
  application.
- **Report numbers honestly.** A saturated evaluation, a cost estimate that was wrong by a
  factor of two, a first diagnosis that was wrong: saying so is what makes the other
  numbers credible.

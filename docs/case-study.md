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
- **Results:** about 10 s and $0.03 per answer, 572 backend and 46 frontend tests, every
  check in CI, and ten problems found by tests, an audit, measurements or the real system,
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

8. **The evaluation stopped being informative.** The 20-question set scored hit@1 1.00 and
   MRR 1.00. Rather than claiming a perfect system, I concluded the set was too easy and
   replaced it: 65 questions over itsdangerous and Flask (ten times more passages),
   labeled with the exact lines that answer, by category, with a held-out test split. On
   Flask, vector search alone drops to hit@1 0.63 and MRR 0.71, and to 0.44 for questions
   in French. Two lessons from reading the misses: tests outrank the code for questions
   about a name, and one "miss" was my own incomplete label (a documentation page about the
   very function asked about). [Analysis](../backend/eval/results/README.md).

9. **The textbook fix made things worse.** Hybrid search (full text with vectors, fused
   with RRF) is the usual answer to exact-name queries, so I built it: a `tsvector` column,
   a configuration that keeps code words, joined forms of snake_case names. Measured on the
   dev split, it lowered the Flask MRR from 0.74 to 0.50: common words matched file names
   (`pull_request_template.md` for "request") and PostgreSQL's ranking ignores word rarity.
   Restricted to code names, it still did nothing useful, because the passages containing a
   name are mostly tests. What worked was the plain fix the baseline pointed to: rank test
   files lower, except for questions about tests. Flask MRR 0.71 → 0.81, confirmed on the
   held-out split with no question worse. Hybrid search stays in the code, off
   ([ADR 0011](adr/0011-rank-tests-lower-hybrid-off.md)). Measuring also caught a bug: an
   escaping mistake had turned the `\b` of the "mentions tests" rule into a control
   character, so the rule never matched; the itsdangerous score gave it away.

10. **A reranker looked worse because my labels were incomplete, then level because the
    sample was small.** Next textbook step: a cross-encoder reranker on the 30 best
    passages. The first measurement said it hurt (Flask dev MRR 0.85 → 0.80). Reading its
    first results, three of its "misses" were correct answers I had not labeled (a guide
    section, a tutorial page, a quickstart example). With the labels completed, it came out
    level over both repositories, and I was about to leave it off. Instead, I fixed a rule
    before looking: on Flask's held-out test split, keep it only if the MRR rises by at
    least 0.05 with more questions up than down. It went from 0.76 to 0.91 (French
    questions 0.42 → 1.00); it is now on
    ([ADR 0012](adr/0012-reranker-decided-by-a-pre-registered-test.md)). Two lessons: an
    evaluation can be wrong in the system's disfavour too, and 18 questions cannot settle a
    difference of a few hundredths.

11. **Streaming could have broken two guarantees; both were caught at design time.**
    A citation cannot be checked before the answer is complete, so the streamed text is a
    labelled draft that the checked answer replaces. And the obvious design (open the
    budget reservation in the request handler, close it when the response ends) fails
    quietly: the response is sent from another task, and the usage meter is a context
    variable that cannot be reset from another task. Each answer now runs in its own
    task, and a test checks that a client that leaves stops the answer, frees its slot
    and still has its tokens recorded. The proxy was the third place to check: Caddy
    compresses text responses, events included, so the streaming route is excluded and a
    CI step times the events through the real stack
    ([ADR 0013](adr/0013-streamed-draft-then-checked-answer.md)).

## Measurements

Answers on `pallets/itsdangerous` (41 files, 99 passages) with Claude Opus 5.5 at effort
`medium`; retrieval on `pallets/flask` (216 files, 1,013 passages):

| | |
|---|---|
| Answer time | about 10 s (7 to 12 s observed): ~1 s retrieval, ~8 s generation |
| Tokens per question | 1,800 to 5,800 in, 400 to 900 out |
| Cost per question | about $0.03; every model call is metered and stored |
| Retrieval on Flask (35 scored questions, line level) | hit@1 0.86, recall@5 0.92, MRR 0.90 (vector search alone: 0.63, 0.82, 0.71) |
| ... by category (MRR) | lookup 1.00, identifier 1.00, French 1.00, multi-file 0.75, paraphrase 0.72 |
| Search time | about 0.6 s median (embedding, database, reranking) |
| First visible result | the passages after about 0.6 s, then the text as it is written |
| Tests | 572 backend (unit and PostgreSQL integration), 46 frontend; CI on every push |

## What I would do next

1. **More questions**, so that effects of a few hundredths become visible on the dev
   split (the reranker's gain only showed on the held-out split), then a full-text ranking
   that knows word rarity (BM25); each kept only if the dev split improves and the
   held-out test split confirms it.
2. **A public deployment** on one server: Docker Compose, Caddy for HTTPS, images built by
   CI, and backups that are restored in a test, not just taken.
3. **More sources and users**: PostgreSQL databases and PDFs as sources, then workspaces
   with per-user budgets (the reservation mechanism already supports a key per tenant).

## What I learned

- **Guarantees beat instructions.** "Do not invent citations" in a prompt reduces the
  problem; resolving IDs on the server removes it. The same goes for budgets: a lock, not
  a check.
- **A test should be able to fail.** Breaking the code on purpose (removing the lock) is
  the quickest way to know a test is worth something.
- **The textbook answer is a hypothesis.** Hybrid search is what everyone recommends for
  exact names; on this corpus it made retrieval worse, and a two-line change did better.
  Only the measurement could tell, and only reading the misses could explain why.
- **Look at the real system.** Three of the ten problems above (encoding, translation,
  misleading bars) passed every test and were obvious within minutes of using the real
  application.
- **Report numbers honestly.** A saturated evaluation, a cost estimate that was wrong by a
  factor of two, a first diagnosis that was wrong: saying so is what makes the other
  numbers credible.

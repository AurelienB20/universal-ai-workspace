# Retrieval results

Reports written by `python -m uaw.evaluation <set> --top-k 10 --json <file>`. Compare a new
run with a reference with `python -m uaw.evaluation.compare <reference> <new>`.

| File | What |
|---|---|
| `baseline-<set>[-dev\|-test].json` | the current production setting: compare with it |
| `vector-only-<set>[-dev\|-test].json` | the first reference, vector search alone |
| `experiments/` | the runs behind each decision below |

`-dev` files hold the dev split (compare with them while tuning), `-test` files the test
split (run once per finished change), the others every question.

## Current setting: vector search, test files ranked lower

| Set (line level) | hit@1 | recall@5 | MRR |
|---|---|---|---|
| pallets/flask, 35 questions | 0.71 | 0.87 | 0.81 |
| pallets/itsdangerous, 24 questions | 0.92 | 0.81 | 0.94 |

Flask by category (MRR): lookup 0.94, identifier 0.94, multi-file 0.87, paraphrase 0.67,
cross-lingual 0.58.

## Experiment 1: hybrid search and test files (2026-10-24)

Hypothesis from the baseline below: questions about a name rank poorly because tests,
which repeat names, outrank the code. Two remedies were measured on the dev split, then the
kept one once on the test split. Runs: `experiments/2026-10-24-hybrid/`.

| Flask, dev split (18 questions) | hit@1 | MRR |
|---|---|---|
| Vector search (reference) | 0.67 | 0.738 |
| Hybrid, full text on every word, RRF (text weight 0.5 / 1 / 2) | 0.44 / 0.33 / 0.28 | 0.567 / 0.503 / 0.435 |
| Hybrid, full text on the question's code names only (weight 1) | 0.56 | 0.663 |
| Vector search, test files ranked lower (×0.5) | **0.78** | **0.847** |
| Both | 0.78 | 0.847 |

- **Full text on every word made retrieval worse.** Reading its results: common words match
  file names ("request" brings up `pull_request_template.md`, "error" a test file named
  `typing_error_handler.py`), and PostgreSQL's `ts_rank` has no notion of word rarity, so
  frequent words outweigh rare ones.
- **Full text on code names only still did not help:** the passages that contain a name
  are mostly tests. Once tests rank lower, it no longer changes any result. It stays
  available (`RETRIEVAL_MODE=hybrid`) but off; a ranking with word rarity (BM25) would be
  the next thing to try.
- **Ranking test files lower** (their fused score × 0.5) raised the dev MRR by 0.11, at the
  cost of one question, the one that asks where the tests are. Questions that mention
  tests are therefore exempt, which removed that loss. 0.3 gave the same results as 0.5.
- **Confirmed once on the test split**, only gains: Flask MRR 0.68 → 0.76 (5 questions up,
  none down; exact names 0.80 → 1.00), itsdangerous 0.88 → 0.92 (1 up, none down). Enabled
  in production: `RETRIEVAL_TEST_WEIGHT=0.5`.
- A bug found by measuring: the first version of the "question mentions tests" rule
  never matched (an escaping mistake had turned `\b` into a control character), which the
  itsdangerous score showed. It is now covered by an integration test.

## Baseline: vector search only (2026-10-24)

Configuration: `voyage-code-3` embeddings (1,024 dimensions), cosine similarity over the
latest snapshot, pgvector HNSW index with iterative scans, top 10 passages. No full-text
search, no reranking. Line-level scores (a passage counts only if it overlaps the lines that
answer):

| Set | Scored questions | hit@1 | recall@5 | MRR |
|---|---|---|---|---|
| pallets/flask (216 files, 1,013 passages) | 35 | 0.63 | 0.82 | 0.71 |
| pallets/itsdangerous (41 files, 99 passages) | 24 | 0.88 | 0.81 | 0.92 |

Flask, by category (line level):

| Category | Questions | hit@1 | recall@5 | MRR |
|---|---|---|---|---|
| lookup | 8 | 0.88 | 1.00 | 0.91 |
| multi-file | 5 | 0.80 | 0.73 | 0.85 |
| identifier | 8 | 0.62 | 0.94 | 0.72 |
| paraphrase | 8 | 0.50 | 0.75 | 0.62 |
| cross-lingual | 6 | 0.33 | 0.58 | 0.44 |

## What it shows

1. **The first set was not measuring much.** On the small repository, retrieval stays near
   the ceiling (MRR 0.92). On Flask, with ten times more passages competing, the first
   passage is the right one only 63 % of the time.

2. **Questions asked with the code's own words work; the others do not.** `lookup` reaches
   MRR 0.91, but a question without the code's vocabulary (`paraphrase`) drops to 0.62:
   "keep a value for the duration of one request" does not find the `g` object at all.

3. **Exact names are found, but tests outrank the code.** For `identifier` questions, the
   right passage is in the top 5 almost every time (recall 0.94) but first in 62 % of the
   cases. Looking at the misses: for "What does PROPAGATE_EXCEPTIONS change?", the four
   passages above the code that handles it are tests that mention the setting. Tests repeat
   names, so they look close to a question about a name. Two leads to measure: full-text
   search with field weighting (hybrid search), and ranking tests below source and docs.

4. **Questions in French are the weakest point** (MRR 0.44) on a repository written in
   English: the passages are found, but lower, and one question (websockets) is missed
   entirely. Worth measuring: translating the question before embedding it.

5. **For multi-file questions, the first file is found, the others less often:** first rank
   is good (MRR 0.85), but only 73 % of the evidence is in the top 5. A reranker, or more
   passages given to the model, would help there.

6. **Similarity alone cannot say "this repository does not contain the answer".** Questions
   without an answer still get a best similarity of 0.49 to 0.54, while questions with an
   answer have a median of about 0.6; but 3 answerable questions out of 35 on Flask (and 3
   out of 24 on itsdangerous) score as low as the highest unanswerable one. A threshold
   would reject real questions; the model's `insufficient_context` flag remains the guard.

## Caveats

- 35 scored questions on Flask: one question moves a category score by 0.12 to 0.20 and the
  overall score by about 0.03. Differences smaller than that are noise.
- Labels were written by one person (with an assistant) and checked automatically against
  the indexed files; a second reviewer would make them stronger. A missing label makes
  retrieval look worse than it is: the first run counted a miss for `after_this_request`
  because its first result, a documentation page about that very function
  (`docs/patterns/deferredcallbacks.rst`), was not labeled. Adding it raised the Flask MRR
  from 0.69 to 0.71. Misses are therefore read one by one before drawing conclusions.
- This first run printed every question, test split included. From now on, changes are
  compared on the dev split only, and the test split is run once per finished change.

## Next

In this order, each kept only if the dev split improves and the test split confirms it:

1. Hybrid search: PostgreSQL full text alongside vectors, merged with reciprocal rank
   fusion (targets `identifier`, then `paraphrase`).
2. Reranking the top passages (targets `multi-file` and first-rank precision).
3. Translating non-English questions before embedding them (targets `cross-lingual`).

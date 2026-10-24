# ADR 0012: Answers use a reranker, decided by a pre-registered test

- **Status:** accepted
- **Date:** 2026-10-24

## Context

After test files were ranked lower (ADR 0011), the weakest categories were paraphrases,
questions in French and multi-file questions. A reranker (a cross-encoder that reads the
question and each passage together) is the usual next step for first-rank precision.
Voyage offers one (`rerank-3`, and `rerank-3-lite` for lower latency), priced at a
fraction of a cent per question.

## Decision

The 30 best chunks of the current ranking (`RERANK_CANDIDATES`) are scored by `rerank-3`
(`RERANK_MODEL`), test files are down-weighted the same way, and the best are kept. The
reranker's score is stored next to the cosine similarity in each answer's trace and shown
in the evidence panel. Its tokens count in the Voyage budget, reserved before the question
starts. Enabled by default.

## How it was decided

1. **Dev split, first run:** the reranker looked worse (Flask MRR 0.847 → 0.796). Reading
   its first results showed three of its "misses" were valid answers missing from the
   labels. The labels were completed (dev questions only, judged on their content) and
   both settings measured again.
2. **Dev split, complete labels:** Flask +0.04 (3 questions up, 2 down), itsdangerous
   −0.07 (2 questions down): level overall, too few questions to tell an effect from noise.
3. **A test fixed in advance:** Flask is the reference repository; on its test split (17
   questions never used for tuning), keep the reranker only if the MRR rises by at least
   0.05 with more questions up than down. Result: **0.76 → 0.91**, 4 up, 2 down by one
   rank. Questions in French went from 0.42 to 1.00, and a question the vector search
   missed entirely (websockets) came first.
4. **Control, itsdangerous test split** (reported, not deciding): 0.92 → 0.93, no question
   worse.

## Alternatives considered

- **No reranker:** faster (about 0.24 s per search instead of about 0.6 s), but Flask MRR
  0.81 instead of 0.90 over all its questions.
- **`rerank-3-lite`:** no better than `rerank-3` on the dev split, and no faster.

## Consequences

- Flask, all 35 questions: MRR 0.81 → 0.90; questions in French and exact names reach 1.00.
- itsdangerous, all 24 questions: 0.94 → 0.91, from two dev questions; one is a real
  reranker error (it takes "timing attack" for the timestamp code and pushes the
  constant-time comparison down).
- About 0.4 s more per search, on answers that take about 10 s: a few percent. The plain
  `/search` route doubles its time.
- One more call per question to Voyage (same provider and key as the embeddings), about
  $0.0006.

## Revisit when

The question set grows (effects of a few hundredths become visible), the reranker's errors
on small repositories show up in use, or a newer reranker model is available.

## Evidence

[`embeddings/voyage.py`](../../backend/src/uaw/embeddings/voyage.py) (`VoyageReranker`),
[`retrieval/retriever.py`](../../backend/src/uaw/retrieval/retriever.py),
[measurements](../../backend/eval/results/README.md),
[tests](../../backend/tests/integration/test_rerank.py)

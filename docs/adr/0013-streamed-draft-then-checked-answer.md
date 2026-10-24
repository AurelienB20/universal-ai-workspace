# ADR 0013: Answers are streamed as a draft, then replaced by the checked answer

- **Status:** accepted
- **Date:** 2026-10-24

## Context

An answer takes about 10 s, almost all of it Claude writing. Until now the interface
showed a timer, then the whole answer at once. Streaming the text as it is written is
the obvious fix, but two guarantees must survive it: every citation is resolved by the
server and invented ones are removed (ADR 0006), and every answer stays within the
concurrency limit and the reserved budget, with its tokens recorded (ADR 0009). A
streamed citation cannot be checked before the answer is complete, and the model's
answer is a JSON document (structured output), so what arrives is pieces of JSON.

## Decision

`POST /ask/stream` sends server-sent events: `sources` (the passages, about 0.6 s after the
question), then `delta` (draft text), then `done`, the answer exactly as `POST /ask` returns
it, which replaces the draft. `reset` discards the draft when the model is replaced mid-answer
(refusal fallback), and `error` ends a stream that fails after it started. Errors known
before the stream (unknown repository, busy server, budget spent) stay HTTP errors.

- The draft text is read out of the JSON as it arrives, by a small decoder of the
  `answer` string (escapes and surrogate pairs cut anywhere). Structured output is kept.
- The draft is labelled as such, and its `[Sn]` markers link only to passages that were
  retrieved; the checked answer then removes any the model invented.
- Each streamed answer runs in its own task, which holds the concurrency slot, the budget
  reservation and the usage record until the end: the usage meter is a context variable,
  which must be set and reset in the same task. A client that leaves cancels the task,
  which stops Claude; the tokens already generated are still recorded.
- The Next.js server passes the events on without reading the body, and aborts the backend
  request when the browser leaves. Caddy does not compress this route: a compressor holds
  small events back.

## Alternatives considered

- **Free text instead of structured output while streaming:** simpler to stream, but no
  reliable "insufficient context" signal, and no strict validation of the result.
- **Checking citations in the browser while streaming:** the browser would decide what
  counts as a valid citation; the server stays the only authority.
- **WebSockets:** two-way, which this does not need, and harder to pass through proxies
  and rate limits than one HTTP request.
- **EventSource in the browser:** cannot send a POST with a body; `fetch` reads the same
  events.

## Consequences

- The sources appear after about 0.6 s and the text a few seconds later; the total time is
  unchanged.
- For a moment the visitor sees a draft that may cite a passage the final answer drops. It
  is labelled, and the checked answer replaces it.
- When a client leaves early, output tokens are estimated from the text received (the API
  reports them only at the end): a lower bound, since thinking tokens are not visible.
- `POST /ask` stays, for cached suggested answers and the evaluation.

## Evidence

[`api/ask.py`](../../backend/src/uaw/api/ask.py),
[`generation/json_stream.py`](../../backend/src/uaw/generation/json_stream.py),
[`generation/claude.py`](../../backend/src/uaw/generation/claude.py) (`stream`),
[stream tests](../../backend/tests/integration/test_ask_stream.py) (a client that leaves frees
its limits and its usage is recorded),
[`lib/sse.ts`](../../frontend/src/lib/sse.ts),
[CI check through Caddy and Next.js](../../.github/ci/check_stream.py)

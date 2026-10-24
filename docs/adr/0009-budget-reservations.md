# ADR 0009: Daily budgets are reserved atomically, under a PostgreSQL lock

- **Status:** accepted
- **Date:** 2026-10-24

## Context

A public demo needs a hard daily ceiling on model spending. The first version checked
"tokens spent today < budget" before each question. An audit pointed out that this is a
check-then-act race: the tokens are only recorded once the answer is done (about 10 s
later), so 20 simultaneous questions all see the same total and all pass. The budgets
were also optional, and off by default.

## Decision

Before it starts, each question reserves its worst-case tokens (`ASK_RESERVED_LLM_TOKENS`,
`QUERY_RESERVED_EMBEDDING_TOKENS`) in a `budget_reservations` table. The check
"spent + reserved + needed ≤ budget" and the insertion run in one transaction under a
`pg_advisory_xact_lock` per provider, taken in a fixed order. The real usage is recorded
before the reservation is released, so tokens are always counted by one or the other.
Reservations expire after 10 minutes, so a crashed process cannot block the budget. Both
budgets are required when `APP_ENV=production`, and at most `MAX_CONCURRENT_ASKS`
questions run at a time.

## Alternatives considered

- **Check, then act** (the first version): races under concurrency.
- **A counter in Redis:** atomic, but a service added for this alone (see ADR 0004).
- **Serializing all questions:** correct, but one question at a time.

## Consequences

- Simultaneous requests can never pass together more than the budget. An integration test
  sends 5 questions for a budget of 3: exactly 3 pass. Removing the lock makes it fail
  (checked: 3 failures out of 3 runs).
- The budget is under-used by each reservation's safety margin.
- A spent budget answers `429` until midnight UTC; a budget only held by questions in
  progress answers `429` with a short `Retry-After`.
- The budget counts input and output tokens alike, although output costs five times more:
  1,000,000 tokens is about 140 questions at the measured average (about 5 USD), and up to
  about 10 to 12 USD if every answer were long.

## Revisit when

Budgets per user or per key (multi-tenant): the same reservation, keyed by tenant.

## Evidence

[`usage/tracker.py`](../../backend/src/uaw/usage/tracker.py),
[`storage/usage.py`](../../backend/src/uaw/storage/usage.py),
[concurrency test](../../backend/tests/integration/test_usage.py)

# ADR 0004: No task queue or Redis yet: imports run in the API process

- **Status:** accepted
- **Date:** 2026-10-13

## Context

Imports take seconds to minutes and must not block HTTP requests. Rate limits need a
counter per client. The usual answer is a task queue (Celery, RQ) with Redis, which also
stores the counters. The target is a demo on one small server.

## Decision

Imports run as background tasks inside the API process, with a concurrency limit
(`MAX_CONCURRENT_IMPORTS`). Job state lives in PostgreSQL, so progress survives the
request. Rate limits are token buckets kept in memory. The API therefore runs as a single
process: the Docker image sets `--workers 1` explicitly.

## Alternatives considered

- **Celery or RQ with Redis.** The standard for long jobs, but two more services to run,
  monitor and secure, for a workload of a few imports a day.
- **Rate limits in PostgreSQL.** Shared across processes, but a database write on every
  request, for a single process that does not need it.

## Consequences

- Two fewer services; the whole system is PostgreSQL, the API and the web server.
- A restart interrupts running imports: they are marked as failed at the next startup,
  with a message asking to try again.
- Horizontal scaling of the API is not possible as is.

## Revisit when

Several API instances, or many long imports: move imports to a task queue and rate limits
to a shared store. Daily budgets already hold across processes (see ADR 0009).

## Evidence

[`ingestion/runner.py`](../../backend/src/uaw/ingestion/runner.py),
[`api/ratelimit.py`](../../backend/src/uaw/api/ratelimit.py),
[`backend/Dockerfile`](../../backend/Dockerfile)

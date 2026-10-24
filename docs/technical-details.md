# Technical details

What is implemented, module by module, and how to run, test and deploy it. For the
overview, see the [README](../README.md).

## Implemented

- Project skeleton: FastAPI application factory, typed settings from environment
  variables, logging, `/health` endpoint.
- Strict GitHub repository URL validation (`uaw.connectors.github.url`): accepts only
  `https://github.com/{owner}/{repo}` and rejects other hosts, user info, ports, extra
  paths, query strings, encoded or traversal segments and non-ASCII input. Its unit
  tests include adversarial inputs.
- GitHub connector (`uaw.connectors.github`), not yet exposed through the API:
  - Fetches repository metadata, rejects private or oversized repositories, and pins
    the import to the latest commit SHA of the default branch.
  - Streams the tarball download with a byte cap and an overall timeout. Redirects are
    followed only to allowlisted HTTPS hosts, and the token is never sent outside
    `api.github.com`.
  - Reads the archive in memory without extracting or executing anything. It checks
    gzip integrity, caps the entry count and decompressed size (against decompression
    bombs), reads only regular files and rejects unsafe paths.
  - Indexes supported text files only. It skips dependencies, build output, lockfiles,
    minified, sensitive, binary and non-UTF-8 files, and reports why each file was
    skipped.
- Chunking (`uaw.chunking`):
  - Splits documents into line ranges of at most ~2,000 characters. Each chunk is
    exactly lines `start_line`..`end_line` of its file, which tests check on every
    chunk, including randomly generated documents.
  - Code is cut at top-level definitions, keeping decorators and doc comments with
    them, then between methods, then at blank lines. Small definitions are grouped.
    A block without any boundary is cut with a small overlap.
  - Markdown is split by heading, ignoring headings inside code fences. Each chunk
    keeps its heading breadcrumb (`Install > Windows`).
  - Lines are split on `\n` only, like GitHub does, so citations stay aligned even
    in files containing form feeds or Unicode line separators.
- Storage (`uaw.storage`), PostgreSQL 16 + pgvector, schema managed by Alembic:
  - `repositories` → `snapshots` (one import pinned to a commit SHA) → `documents` →
    `chunks`, with cascading deletes. Citations always point into one immutable snapshot.
  - Integrity is enforced by the database itself: commit SHA format, unique paths per
    snapshot, valid line ranges, and a composite foreign key guaranteeing that a chunk
    and its document belong to the same snapshot.
  - Chunks carry a `vector(1024)` embedding with an HNSW index for cosine distance.
  - The store never commits: the caller owns the transaction, so an import is saved
    entirely or not at all.
  - Integration tests run the real migrations against PostgreSQL, and check that they
    are reversible and match the models exactly.
- Embeddings (`uaw.embeddings`): Voyage `voyage-code-3` client behind a provider-agnostic
  `Embedder` interface.
  - Batches stay within the API limits (texts and tokens per request). Rate limits and
    server errors are retried with exponential backoff and jitter, honouring
    `Retry-After`. Credential and request errors fail immediately.
  - Responses are validated (count, `index`, dimension, finite values), so a vector can
    never be attached to the wrong chunk. Over-long texts raise an error instead of
    being silently truncated.
  - Documents and queries use Voyage's `document` / `query` input types. The embedded
    text starts with the file path (and Markdown section); the stored content stays raw.
- Ingestion pipeline (`uaw.ingestion`) and import API:
  - `POST /imports {"url": ...}` queues an import and returns `202` with a job;
    `GET /imports/{id}` reports its status, stage and progress counters.
  - At most one active import per repository, enforced by a partial unique index:
    a duplicate request returns the running job.
  - Chunks are saved in one transaction, embeddings batch by batch (visible progress,
    no transaction held open during API calls). The snapshot becomes `ready`, and
    therefore searchable, only once every chunk has its vector.
  - Re-importing an already indexed commit reuses its snapshot without any API call.
  - Once a new snapshot is ready, older ones are deleted in the same transaction,
    keeping the `KEEP_SNAPSHOTS` (default 2) most recent: a question still reading the
    previous snapshot is not cut short. Interrupted leftovers go too.
  - Suggested questions with cached answers: `PUT /repositories/{owner}/{name}/suggestions`
    (admin) answers up to 6 questions now, through the same path as `/ask` (budget,
    concurrency, usage), and stores the answers for the latest snapshot, all or
    nothing. `GET` serves them to any allowed key with no model call. Each answer
    keeps its commit, model and generation date, so the interface can say it is
    cached; it is deleted with its snapshot, so it never outlives its sources.
  - `DELETE /repositories/{owner}/{name}` (admin) deletes a repository with all its
    snapshots, refused (`409`) while an import of it is queued or running. Token usage
    records are kept, since that usage was billed.
  - On failure, the partial snapshot is deleted and the job stores a user-facing message;
    unexpected errors are logged in full but shown to users as a generic message.
  - Imports run as background tasks in the API process, with a concurrency limit. A
    restart interrupts them: they are marked as failed at the next startup. This
    assumes a single API process; a dedicated worker queue can replace it later.
- Retrieval (`uaw.retrieval`) and search API, without any LLM:
  - `POST /search {"repository": "owner/name", "query": ..., "top_k": 10}` returns the
    chunks closest to the query (cosine similarity), best first, each with a permanent
    GitHub link to its exact lines at the indexed commit (`?plain=1` for rendered files
    such as Markdown, where line anchors would not work otherwise).
  - Searches only the repository's latest `ready` snapshot. A repository that is not
    imported, or still indexing, gets a `404` without any embedding API call.
  - Refuses (`409`) to compare a query with chunks embedded by another model: their
    vectors are not comparable, and results would be silently meaningless.
  - The HNSW index covers every repository, so a filtered search could keep only the
    nearest chunks of the whole table, then filter them all out. pgvector's iterative
    index scans keep scanning until enough rows match. An integration test forces this
    plan and shows the plain query losing every result.
- Retrieval evaluation (`uaw.evaluation`): a labeled question set
  (`backend/eval/itsdangerous.json`, 20 questions, 3 of them in French) and a command
  that reports hit@k, recall@k (file level) and MRR, and lists the questions whose
  first hit is not relevant. It checks that every labeled file is indexed, so a stale
  label cannot silently count as a miss.
- Grounded answers (`uaw.generation`) with server-validated citations:
  - `POST /ask {"repository": "owner/name", "question": ...}` retrieves the top passages,
    asks Claude (`claude-opus-5-5` by default) and returns a Markdown answer citing
    `[S1]`, `[S2]`…, with each citation's file, line range and permanent link.
  - Structured output: the API enforces a JSON schema `{answer, insufficient_context}`,
    so the model can say the passages do not contain the answer instead of guessing.
  - The stop reason is checked before the content is read: a safety refusal or a
    truncated answer is reported as such, never parsed as a partial answer. Refusals
    are retried server-side on a fallback model (`fallbacks: "default"`, can be disabled).
  - Repository content is untrusted: passages are escaped inside `<source>` tags (a file
    cannot close its tag or forge another source) and the instructions say they are
    data, never commands.
  - Effort is set explicitly (`LLM_EFFORT`, default `medium`): Claude Opus 5.5 always
    thinks, and effort is its only depth control. SDK errors are translated into
    user-facing messages; rate limits and server errors are retried by the SDK.
  - Prompt caching is deliberately not used yet: the stable prefix (instructions) is
    below the minimum cacheable size, and the passages change with every question.
  - Every answer carries its `trace`: each passage shown to the model (path, lines,
    content, similarity score, whether the answer cites it), the citations removed
    because the model invented them, the retrieval and generation times, and the
    tokens. All of it is known while answering, so it costs nothing extra. Answers
    cached before traces existed load with `trace: null`.
- Hardening:
  - API keys (`X-API-Key` header), constant-time comparison. Two roles: the admin key
    (`API_KEY`, required when `APP_ENV=production`) reaches every route; the demo key
    (`DEMO_API_KEY`), meant for a public web interface, can only search and ask
    questions about the `DEMO_REPOSITORIES` and never import (`403`). A repository
    outside the allowlist gets the same `404` as one never imported, so a demo key
    reveals nothing else the server holds.
  - `GET /repositories` lists the searchable repositories (latest ready snapshot,
    commit, file and passage counts), filtered by the caller's role.
  - Per-client rate limits (token bucket, in memory: one API process) on imports,
    searches and questions, and a request body size limit (413), both returning
    `Retry-After` / clear errors.
  - Cost control: Voyage and Claude report the tokens billed for each call to a meter
    held in a context variable, so concurrent operations never mix their counts. Each
    import, search and question saves its usage in `usage_records`, even when it fails
    after being billed. Daily token budgets per provider (required in production)
    refuse new requests with a `429` until midnight UTC.
  - Budgets hold under concurrency: each question and search first reserves its
    worst-case tokens, and the check-then-reserve runs under a PostgreSQL advisory
    lock, so simultaneous requests can never pass together more than the budget (an
    integration test fails without the lock). Reservations are released once the
    usage is recorded, and expire on their own if the process crashes.
  - At most `MAX_CONCURRENT_ASKS` questions run at a time; beyond, a `503` with
    `Retry-After` is returned at once rather than queueing connections.
  - Observability: a request ID per request (`X-Request-ID`, reused from a proxy when
    safe), carried by every log line including background imports; one access log line
    per request with status and duration; JSON logs (`LOG_FORMAT=json`);
    `/health` (liveness) and `/health/ready` (database reachable).
  - Prompt injection: opt-in tests against the real model with passages that try to
    override the instructions, extract the system prompt, or forge tags and citations.
  - Continuous integration (GitHub Actions): lint, strict typing, unit tests,
    integration tests on PostgreSQL + pgvector, and a build of the production image
    (multi-stage, non-root, locked dependencies).
- Web interface (`frontend/`, Next.js + TypeScript + Tailwind), French by default with
  an English switch: pick an indexed repository (or import one, with live progress),
  then ask questions; answers render as Markdown with `[S1]` markers linked to the
  cited lines on GitHub. Suggested questions show cached answers, labelled with their
  generation date. The browser only talks to the Next.js server, which forwards to
  FastAPI with the API key: the key never reaches the browser. A public demo mode
  (demo key, `IMPORTS_ENABLED=false`) and security headers (CSP...) are described in
  `frontend/README.md`.


## Local setup

Requirements: [uv](https://docs.astral.sh/uv/) (it installs Python 3.12 automatically)
and PostgreSQL 16 + pgvector >= 0.8 on 127.0.0.1:5432, from either:

- Docker: `docker compose up -d --wait db`
- or, lighter on Windows, a WSL Debian distribution without Docker:
  `wsl -d Debian -- bash scripts/setup-wsl-postgres.sh` once, then
  `wsl -d Debian -u root -- service postgresql start` (or `stop`).

```bash
cd backend
uv sync                      # create .venv and install locked dependencies
cp .env.example .env         # then set VOYAGE_API_KEY and ANTHROPIC_API_KEY
uv run alembic upgrade head  # create or update the database schema
```

### Run the API

```bash
uv run uvicorn uaw.main:create_app --factory --reload
# http://127.0.0.1:8000/health   http://127.0.0.1:8000/docs
```

### Run the web interface

Needs Node.js 22. With the API running:

```bash
cd frontend
cp .env.example .env.local   # API_URL, and API_KEY if the backend has one
npm install
npm run dev                  # http://localhost:3000
```

### Use the API directly

When `API_KEY` is set, add `-H "X-API-Key: <key>"` to the requests below (imports
need the admin key).

List the searchable repositories:

```bash
curl http://127.0.0.1:8000/repositories
```

Import a repository and follow its progress:

```bash
curl -X POST http://127.0.0.1:8000/imports   -H "content-type: application/json"   -d '{"url": "https://github.com/pallets/itsdangerous"}'
curl http://127.0.0.1:8000/imports/<job id>
```

Search it once the import has succeeded:

```bash
curl -X POST http://127.0.0.1:8000/search -H "content-type: application/json"   -d '{"repository": "pallets/itsdangerous", "query": "How are signatures verified?", "top_k": 5}'
```

Ask a question (needs `ANTHROPIC_API_KEY` too):

```bash
curl -X POST http://127.0.0.1:8000/ask -H "content-type: application/json" \
  -d '{"repository": "pallets/itsdangerous", "question": "How are expired tokens detected?"}'
```

Cache suggested questions with their answers (admin key; billed once, like `/ask`),
then read them for free:

```bash
curl -X PUT http://127.0.0.1:8000/repositories/pallets/itsdangerous/suggestions   -H "content-type: application/json"   -d '{"language": "en", "questions": ["How are expired tokens detected?"]}'
curl "http://127.0.0.1:8000/repositories/pallets/itsdangerous/suggestions?language=en"
```

### Measure retrieval quality

Import `https://github.com/pallets/itsdangerous` (see above), then:

```bash
uv run python -m uaw.evaluation eval/itsdangerous.json             # one Voyage call per question
uv run python -m uaw.evaluation eval/itsdangerous.json --json report.json
```

### Quality checks

```bash
uv run pytest                # unit tests (offline, no API keys needed)
uv run pytest -m db          # integration tests (needs PostgreSQL, see above)
uv run pytest -m live        # tests against the real GitHub, Voyage and Anthropic APIs
uv run alembic check         # fails if the models and migrations disagree
uv run ruff check .          # lint
uv run ruff format --check . # formatting
uv run mypy                  # static type checking (strict)
```

The same checks run on every push in GitHub Actions (`.github/workflows/ci.yml`),
except the live tests, which need API keys.

## Deployment

`backend/Dockerfile` builds the production image (`APP_ENV=production`, JSON logs,
non-root user). It needs `DATABASE_URL`, `API_KEY`, `VOYAGE_API_KEY` and
`ANTHROPIC_API_KEY`. Apply the migrations before starting a new version:

```bash
docker run --rm --env-file backend/.env uaw-backend alembic upgrade head
```

`frontend/Dockerfile` builds the web interface (Next.js standalone server, non-root).
It needs `API_URL` (the backend, as seen from that container) and `API_KEY`: on a
public deployment, the backend's `DEMO_API_KEY`, with `IMPORTS_ENABLED=false`.

Expected topology: a reverse proxy (TLS) in front of the web interface only; the API
is reachable by the web container, not from the internet. Set the API's
`FORWARDED_ALLOW_IPS` to the web container's address so that rate limits apply to the
real client address, and make the reverse proxy set `X-Forwarded-For`. Rate limits are
counted in memory: run a single API process, or move them to a shared store first.

## Project layout

```
backend/
  src/uaw/
    main.py              # FastAPI app factory
    config.py            # settings (pydantic-settings)
    logging_config.py    # text or JSON logs, request IDs
    services.py          # composition root (engine, HTTP clients, pipeline, runner)
    api/                 # HTTP routers, API key, rate limits, middlewares
    domain/              # source-agnostic models (SourceDocument, Chunk, IngestionJob)
    chunking/            # line splitting, boundary scores, markdown sections
    connectors/github/   # url, client (HTTP), archive + filters, connector (policy), links
    embeddings/          # Embedder interface, Voyage client, batching
    ingestion/           # import pipeline and background runner
    retrieval/           # semantic search over the latest ready snapshot
    generation/          # prompt, Claude client, citation checking, answerer
    evaluation/          # retrieval metrics and evaluation command
    usage/               # token meter, usage recording, daily budgets
    storage/             # SQLAlchemy tables, engine/sessions, stores, ChunkSearch
  migrations/            # Alembic migrations
  eval/                  # labeled question sets for retrieval evaluation
  tests/
    unit/                # offline tests, including malicious archives
    integration/         # tests against PostgreSQL (opt-in: -m db)
    live/                # opt-in tests against real services (incl. prompt injection)
  Dockerfile             # production image
frontend/                # Next.js web interface (see frontend/README.md)
.github/workflows/ci.yml # continuous integration
docker-compose.yml       # PostgreSQL + pgvector (and API + web, profile "app")
scripts/                 # PostgreSQL + pgvector in WSL, without Docker
```

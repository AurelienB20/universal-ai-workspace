# Universal AI Workspace

**Connect your data. Ask anything. Get answers backed by evidence.**

A retrieval-augmented generation (RAG) application that lets users connect external data
sources and ask questions in natural language, with answers grounded in, and cited from,
the retrieved content.

The first milestone (MVP 1) targets **public GitHub repositories**: import a repository,
index its code and documentation, and ask questions such as *"Where is authentication
implemented?"* with clickable citations to the exact files and line ranges.

## Status

This project is built incrementally. Only what is listed under *Implemented* works today.

### Implemented

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

### Planned (MVP 1)

| Milestone | Scope |
|---|---|
| 1.8 | Hardening: rate limits, timeouts, error handling |
| 1.9 | Minimal Next.js interface |

Later milestones add hybrid retrieval, reranking and evaluation, then more data sources
(PostgreSQL, PDF), LangGraph orchestration, MCP tools and production infrastructure.

## Key design decision: the LLM never writes citations

Retrieved chunks are passed to the model under opaque IDs (`S1`, `S2`, …). The model may
only reference those IDs. The server maps each ID to its file path, line range and pinned
commit, and discards any ID that was not retrieved. As a result, invented file names or
line numbers cannot appear in a citation: the code guarantees it, rather than the prompt
merely asking for it.

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

## Project layout

```
backend/
  src/uaw/
    main.py              # FastAPI app factory
    config.py            # settings (pydantic-settings)
    logging_config.py
    services.py          # composition root (engine, HTTP clients, pipeline, runner)
    api/                 # HTTP routers (health, imports, search, ask)
    domain/              # source-agnostic models (SourceDocument, Chunk, IngestionJob)
    chunking/            # line splitting, boundary scores, markdown sections
    connectors/github/   # url, client (HTTP), archive + filters, connector (policy), links
    embeddings/          # Embedder interface, Voyage client, batching
    ingestion/           # import pipeline and background runner
    retrieval/           # semantic search over the latest ready snapshot
    generation/          # prompt, Claude client, citation checking, answerer
    evaluation/          # retrieval metrics and evaluation command
    storage/             # SQLAlchemy tables, engine/sessions, SnapshotStore, JobStore, ChunkSearch
  migrations/            # Alembic migrations
  eval/                  # labeled question sets for retrieval evaluation
  tests/
    unit/                # offline tests, including malicious archives
    integration/         # tests against PostgreSQL (opt-in: -m db)
    live/                # opt-in tests against real services
docker-compose.yml       # local PostgreSQL + pgvector
```

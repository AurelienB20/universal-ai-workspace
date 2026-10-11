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

### Planned (MVP 1)

| Milestone | Scope |
|---|---|
| 1.3 | Chunking of code and Markdown with exact line ranges |
| 1.4 | PostgreSQL + pgvector storage (Docker Compose), migrations |
| 1.5 | Embeddings (Voyage `voyage-code-3`) and ingestion pipeline with job tracking |
| 1.6 | Retrieval, plus a small labeled question set to measure recall@k |
| 1.7 | Grounded answer generation (Claude) with server-validated citations |
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

Requirements: [uv](https://docs.astral.sh/uv/). uv installs Python 3.12 automatically.

```bash
cd backend
uv sync                      # create .venv and install locked dependencies
cp .env.example .env         # optional, every setting has a default
```

### Run the API

```bash
uv run uvicorn uaw.main:create_app --factory --reload
# http://127.0.0.1:8000/health   http://127.0.0.1:8000/docs
```

### Quality checks

```bash
uv run pytest                # unit tests (offline, no API keys needed)
uv run pytest -m live        # tests against the real GitHub API (network)
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
    api/                 # HTTP routers
    domain/              # source-agnostic models (SourceDocument)
    connectors/github/   # url, client (HTTP), archive + filters, connector (policy)
  tests/
    unit/                # offline tests, including malicious archives
    live/                # opt-in tests against real services
```

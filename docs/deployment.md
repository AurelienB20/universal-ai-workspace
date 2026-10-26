# Deploying the public demo

One server runs everything: Caddy (HTTPS), the web interface, the API and PostgreSQL,
with Docker Compose. The same stack runs in CI on every push (`deploy` job), so what is
described here is tested, not just written.

```
Internet ──443──► Caddy ──► web (Next.js, demo key) ──► api (FastAPI) ──► db (PostgreSQL)
                                                          ▲
                              server shell ──127.0.0.1:8000┘ (admin key)
```

Only Caddy listens on public ports. The web server holds the **demo** key; the admin key
is only used from the server itself.

## 1. The server

- A VPS with **2 GB of RAM at least, 4 GB recommended** (PostgreSQL, the API and the web
  server together), 20 GB of disk, Ubuntu 24.04 or Debian 12.
- A domain or subdomain, with an `A` record (and `AAAA` for IPv6) pointing to the server.
- Ports 80 and 443 open; SSH restricted to keys.

Install Docker Engine and the Compose plugin from Docker's repository
(<https://docs.docker.com/engine/install/>), then:

```bash
git clone https://github.com/AurelienB20/universal-ai-workspace.git
cd universal-ai-workspace/deploy
cp .env.example .env
chmod 600 .env
```

## 2. Configure

Fill in every value of `deploy/.env`. Generate each secret with `openssl rand -hex 32`:
`POSTGRES_PASSWORD`, `API_KEY` (admin) and `DEMO_API_KEY` (different from the admin key).
Set `DOMAIN`, the provider keys, and the daily budgets: the API refuses to start in
production without them.

The images come from GitHub's container registry, published by CI from `main`. If the
packages are private, log in once with a token that can read packages:
`docker login ghcr.io -u AurelienB20`. Making the two packages public (GitHub, Packages,
Package settings) avoids it.

## 3. Start and check

```bash
docker compose -f docker-compose.prod.yml up -d --wait
./smoke-test.sh https://demo.example.com
```

The first start obtains the HTTPS certificate (DNS must already point to the server). The
smoke test checks HTTPS and its redirect, the security headers, that imports are removed
from the public site, that streamed answers reach the API, that the API needs a key and is
only reachable from the server, and that the demo key cannot import. It calls no model
provider. (CI also checks, with a fake API, that Caddy and Next.js pass a streamed answer
on event by event: Caddy must not compress `/api/ask/stream`, see the `Caddyfile`.)

## 4. Import the demo repositories

From the server, with the admin key (the API listens on `127.0.0.1:8000` only):

```bash
source .env
curl -X POST http://127.0.0.1:8000/imports -H "X-API-Key: $API_KEY" \
  -H "content-type: application/json" -d '{"url": "https://github.com/pallets/itsdangerous"}'
curl http://127.0.0.1:8000/imports/<job id> -H "X-API-Key: $API_KEY"
```

List every repository you import in `DEMO_REPOSITORIES` (comma-separated), then restart
the API: `docker compose -f docker-compose.prod.yml up -d api`.

Then cache the suggested questions, once per language (billed once, about $0.03 per
question; visitors then read them for free):

```bash
curl -X PUT http://127.0.0.1:8000/repositories/pallets/itsdangerous/suggestions \
  -H "X-API-Key: $API_KEY" -H "content-type: application/json" \
  -d '{"language": "en", "questions": ["How are expired tokens detected?", "How is a signature verified?", "What is the salt used for?"]}'
```

Repeat with `"language": "fr"` and French questions. Suggestions belong to a snapshot:
after re-importing a repository, generate them again.

### Imports by visitors (optional)

With `PUBLIC_IMPORTS_ENABLED=true` in `.env`, visitors can import their own public
repository (see [ADR 0014](adr/0014-public-imports-private-capped-temporary.md)). Each one
is private to its visitor and deleted after `VISITOR_ACCESS_HOURS`. Raise
`DAILY_EMBEDDING_TOKEN_BUDGET` first: it must exceed what visitors can spend in a day
(`VISITOR_IMPORTS_PER_DAY` × `VISITOR_MAX_IMPORT_TOKENS`), or the API refuses to start.

| Setting | Default | |
|---|---|---|
| `VISITOR_ACCESS_HOURS` | 24 | then the repository is deleted, unless another visitor still reads it |
| `VISITOR_MAX_REPO_SIZE_MB`, `VISITOR_MAX_FILES` | 20, 300 | stricter than the admin's limits |
| `VISITOR_MAX_IMPORT_TOKENS` | 400,000 | estimated before any is spent (about 0.07 USD) |
| `VISITOR_IMPORTS_PER_VISITOR_PER_DAY` | 2 | counted in the database |
| `VISITOR_IMPORTS_PER_DAY` | 20 | all visitors, counted in the database |
| `RATE_LIMIT_VISITOR_IMPORTS_PER_DAY` | 3 | per address, in memory |
| `VISITOR_IMPORT_QUEUE` | 3 | imports waiting behind the running one |
| `VISITOR_QUESTIONS_PER_DAY` | 15 | per visitor, about their own repositories |

To switch them off again, set `PUBLIC_IMPORTS_ENABLED=false` and restart the API and the
web server (`docker compose -f docker-compose.prod.yml up -d --wait`): the import panel
disappears, and the repositories already imported still expire on time.

## 5. Backups

```bash
./backup.sh                  # writes backups/uaw-<UTC time>.dump, and checks it is readable
./restore.sh backups/uaw-<…>.dump            # restores into uaw_restored and compares counts
./restore.sh --replace backups/uaw-<…>.dump  # replaces the live database (asks to confirm)
```

Run the backup every night, and copy the files off the server (a lost server loses its
local backups too):

```cron
15 3 * * * cd /home/deploy/universal-ai-workspace/deploy && ./backup.sh >> backups/backup.log 2>&1
```

Check a restore regularly with `./restore.sh <file>` (without `--replace`): it never
touches the live database. Backups older than 14 days are deleted (`KEEP_DAYS`).

## 6. Update

```bash
git pull                                            # compose file and scripts
docker compose -f docker-compose.prod.yml pull      # images published by CI
docker compose -f docker-compose.prod.yml up -d --wait
./smoke-test.sh https://demo.example.com
```

Migrations run automatically before the API starts (`migrate` service). To pin a version
instead of `latest`, set `BACKEND_IMAGE` and `FRONTEND_IMAGE` to `…:<commit sha>` in
`.env`; rolling back is the same with the previous SHA (and a restore if a migration
changed the schema).

## 7. Operate

```bash
docker compose -f docker-compose.prod.yml ps              # state and health
docker compose -f docker-compose.prod.yml logs -f api     # JSON logs, one request ID per request
```

Logs are rotated (3 files of 10 MB per service). Token usage is recorded in the
`usage_records` table; daily budgets stop new questions with a `429` until midnight UTC.

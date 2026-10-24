# ADR 0008: The browser talks to the Next.js server, which holds the API key

- **Status:** accepted
- **Date:** 2026-10-24

## Context

The API is protected by keys, and every question spends money. A key sent to the browser
would be public. The API should also not be reachable from the internet at all.

## Decision

The browser only calls the Next.js server's Route Handlers (`/api/...`). They add the API
key (a server-side environment variable), forward the client address so that rate limits
apply per visitor, check the request size, and validate path segments before building
the backend URL. On a public deployment the web server holds the **demo** key, which can
only question an allowlist of repositories and never import; `IMPORTS_ENABLED=false`
removes the import panel and routes. Every page carries a Content Security Policy and
`translate="no"`, since the interface has its own French and English versions and a
browser's automatic translation rewrote code names.

## Alternatives considered

- **The browser calls the API directly, with CORS.** The key would be visible, or the API
  would have to be public and unauthenticated.
- **A separate gateway (nginx rules, API gateway).** The same result with one more piece
  to configure, for two routes.

## Consequences

- The key never reaches the browser, and the API is only reachable from the web container.
- One more network hop per request, and forwarding routes to keep in sync with the API.
- Even if `IMPORTS_ENABLED` were forgotten, the backend still refuses imports with the
  demo key (`403`).

## Revisit when

User accounts: server-side sessions mapping each user to a key or a role, in the same
architecture.

## Evidence

[`frontend/src/lib/backend.ts`](../../frontend/src/lib/backend.ts),
[`api/security.py`](../../backend/src/uaw/api/security.py),
[`next.config.ts`](../../frontend/next.config.ts)

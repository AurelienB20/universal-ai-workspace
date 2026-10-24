# Web interface

Next.js (App Router), TypeScript, Tailwind CSS. French by default, English available
(language switch, remembered in the browser).

```
Browser ──► Next.js server (/api/repositories, /api/ask/stream, /api/imports...) ──► FastAPI
              adds X-API-Key (server-side variable), forwards the client address
```

The visitor picks an indexed repository (or imports one), then asks questions.
Suggested questions show answers generated in advance, labelled as cached with their
generation date.

## Public demo mode

Give the Next.js server the backend's `DEMO_API_KEY` (never the admin key) and set
`IMPORTS_ENABLED=false`: the import panel disappears and `/api/imports` returns `404`.
The backend refuses imports with that key anyway (`403`); this only avoids showing a
form that cannot work. The setting is read at request time (`/api/config`), so one
Docker image serves both modes.

## Security headers

Every response carries a Content Security Policy (same-origin only, no framing, no
plugins), `X-Content-Type-Options`, `Referrer-Policy`, `X-Frame-Options` and
`Permissions-Policy` (see `next.config.ts`). Scripts allow `'unsafe-inline'`, as Next.js
documents for statically rendered pages; a nonce would force rendering every request.
HSTS belongs to the TLS reverse proxy.

The browser never calls FastAPI directly: the API key stays on the Next.js server and
there is no CORS to configure. Answers are rendered as Markdown without raw HTML (they
derive from untrusted repository content), and `[S1]` markers become links to the cited
lines on GitHub.

## Run locally

Start the backend first (see the main README), then:

```bash
cp .env.example .env.local   # API_URL, and API_KEY if the backend has one
npm install
npm run dev                  # http://localhost:3000
```

## Checks

```bash
npm run lint
npm run typecheck
npm test                     # Vitest: citation links, proxy, translations
npm run build
```

## Layout

```
src/
  app/            # page, layout, Route Handlers (api/) that proxy to the backend
  components/     # Workspace, RepositoryPicker, ImportPanel (progress polling),
                  # AskPanel (suggestions), AnswerView (cached badge)
  i18n/           # fr/en messages, language provider, error messages
  lib/            # backend proxy (server only), API client, citation links, types
```

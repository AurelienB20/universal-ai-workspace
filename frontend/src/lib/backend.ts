import "server-only";

// Server-side calls from the Next.js Route Handlers to the FastAPI backend.
//
// The browser never talks to FastAPI directly: the API key stays on this server,
// and there is no CORS to configure. The client address is forwarded so that the
// backend rate limits each user, not this server.

export const MAX_BODY_BYTES = 16 * 1024;
// Answers take ~10 s with Claude Opus; the backend's own LLM timeout is 120 s.
const TIMEOUT_MS = 150_000;

export interface BackendConfig {
  url: string;
  apiKey: string | undefined;
}

export function backendConfig(): BackendConfig {
  return {
    url: (process.env.API_URL ?? "http://127.0.0.1:8000").replace(/\/+$/, ""),
    apiKey: process.env.API_KEY || undefined,
  };
}

/**
 * The client address to forward: the last X-Forwarded-For entry, written by the
 * nearest proxy. Next.js fills the header with the socket address when it is
 * absent; in production it must run behind a reverse proxy that sets it.
 */
export function clientAddress(headers: Headers): string | undefined {
  const entries = (headers.get("x-forwarded-for") ?? "")
    .split(",")
    .map((entry) => entry.trim())
    .filter(Boolean);
  return entries.at(-1);
}

function jsonError(status: number, detail: string): Response {
  return Response.json({ detail }, { status });
}

/**
 * Forward ``request`` to ``path`` on the backend and return its response as is
 * (status, JSON body, Retry-After and X-Request-ID headers).
 */
export async function forward(
  request: Request,
  path: string,
  config: BackendConfig = backendConfig(),
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const sent = await send(request, path, config, fetchImpl, "application/json");
  if ("error" in sent) return sent.error;
  const { response } = sent;
  return new Response(await response.text(), {
    status: response.status,
    headers: passedHeaders(response),
  });
}

/**
 * Like ``forward``, for a backend route that answers with server-sent events: the
 * events are passed on as they arrive, never buffered. When the browser goes away,
 * the backend request is aborted too, which stops the answer being written.
 */
export async function forwardStream(
  request: Request,
  path: string,
  config: BackendConfig = backendConfig(),
  fetchImpl: typeof fetch = fetch,
): Promise<Response> {
  const sent = await send(request, path, config, fetchImpl, "text/event-stream", request.signal);
  if ("error" in sent) return sent.error;
  const { response } = sent;
  const headers = passedHeaders(response);
  if (!response.ok || !headers.get("content-type")?.startsWith("text/event-stream")) {
    // An error found before the answer started: JSON, as with ``forward``.
    return new Response(await response.text(), { status: response.status, headers });
  }
  // no-transform: no compression, which would hold the events back.
  headers.set("cache-control", "no-cache, no-transform");
  headers.set("x-accel-buffering", "no");
  return new Response(response.body, { status: response.status, headers });
}

// The backend's response, or the error to return when there is none.
type Sent = { response: Response } | { error: Response };

async function send(
  request: Request,
  path: string,
  config: BackendConfig,
  fetchImpl: typeof fetch,
  accept: string,
  clientSignal?: AbortSignal,
): Promise<Sent> {
  let body: string | undefined;
  if (request.method !== "GET") {
    body = await request.text();
    if (new TextEncoder().encode(body).length > MAX_BODY_BYTES) {
      return { error: jsonError(413, "Request body too large.") };
    }
  }

  const headers = new Headers({ accept });
  if (body !== undefined) headers.set("content-type", "application/json");
  if (config.apiKey) headers.set("x-api-key", config.apiKey);
  const client = clientAddress(request.headers);
  if (client) headers.set("x-forwarded-for", client);

  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  try {
    const response = await fetchImpl(`${config.url}${path}`, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: clientSignal ? AbortSignal.any([clientSignal, timeout]) : timeout,
    });
    return { response };
  } catch {
    return { error: jsonError(502, "The backend is unreachable.") };
  }
}

function passedHeaders(response: Response): Headers {
  const passed = new Headers({
    "content-type": response.headers.get("content-type") ?? "application/json",
  });
  for (const name of ["retry-after", "x-request-id"]) {
    const value = response.headers.get(name);
    if (value) passed.set(name, value);
  }
  return passed;
}

/**
 * Whether this interface offers imports. Set IMPORTS_ENABLED=false on a public demo,
 * whose server holds the backend's demo key: the backend would refuse imports anyway
 * (403), so the panel and the proxy routes are removed rather than left failing.
 */
export function importsEnabled(env: Record<string, string | undefined> = process.env): boolean {
  return env.IMPORTS_ENABLED?.trim().toLowerCase() !== "false";
}

export function notFound(): Response {
  return jsonError(404, "Not found.");
}

// Same rules as the backend (uaw.connectors.github.url): nothing else can reach the path.
const OWNER = /^[A-Za-z0-9][A-Za-z0-9-]{0,38}$/;
const REPO = /^[A-Za-z0-9._-]{1,100}$/;
const LANGUAGES = new Set(["fr", "en"]);

/** The backend path of a repository's suggestions, or null if a part is invalid. */
export function suggestionsPath(owner: string, name: string, language: string | null): string | null {
  if (!OWNER.test(owner) || !REPO.test(name) || name === "." || name === "..") return null;
  if (language === null || !LANGUAGES.has(language)) return null;
  return `/repositories/${owner}/${name}/suggestions?language=${language}`;
}

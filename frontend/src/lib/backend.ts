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
  let body: string | undefined;
  if (request.method !== "GET") {
    body = await request.text();
    if (new TextEncoder().encode(body).length > MAX_BODY_BYTES) {
      return jsonError(413, "Request body too large.");
    }
  }

  const headers = new Headers({ accept: "application/json" });
  if (body !== undefined) headers.set("content-type", "application/json");
  if (config.apiKey) headers.set("x-api-key", config.apiKey);
  const client = clientAddress(request.headers);
  if (client) headers.set("x-forwarded-for", client);

  let response: Response;
  try {
    response = await fetchImpl(`${config.url}${path}`, {
      method: request.method,
      headers,
      body,
      cache: "no-store",
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch {
    return jsonError(502, "The backend is unreachable.");
  }

  const passed = new Headers({
    "content-type": response.headers.get("content-type") ?? "application/json",
  });
  for (const name of ["retry-after", "x-request-id"]) {
    const value = response.headers.get(name);
    if (value) passed.set(name, value);
  }
  return new Response(await response.text(), { status: response.status, headers: passed });
}

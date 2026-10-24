// Browser-side calls. They go to this app's Route Handlers (/api/...), which
// forward them to the backend with the API key (see lib/backend.ts).

import type { Answer, ImportJob } from "./types";

export class ApiError extends Error {
  constructor(
    // 0 when the request never got a response (network error).
    readonly status: number,
    // The backend's message, when it sent a readable one (English).
    readonly detail: string | null,
    readonly retryAfterSeconds: number | null,
  ) {
    super(detail ?? `HTTP ${status}`);
  }
}

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...init,
      headers: { "content-type": "application/json", ...init?.headers },
    });
  } catch {
    throw new ApiError(0, null, null);
  }
  if (!response.ok) {
    const retryAfter = Number(response.headers.get("retry-after"));
    throw new ApiError(
      response.status,
      await readDetail(response),
      Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
    );
  }
  return (await response.json()) as T;
}

/** FastAPI errors are {"detail": "..."}, or a list of field errors for a 422. */
async function readDetail(response: Response): Promise<string | null> {
  try {
    const body: unknown = await response.json();
    const detail = (body as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && typeof detail[0]?.msg === "string") return detail[0].msg;
  } catch {
    // not JSON
  }
  return null;
}

export function startImport(url: string): Promise<ImportJob> {
  return call<ImportJob>("/api/imports", { method: "POST", body: JSON.stringify({ url }) });
}

export function getImport(id: string): Promise<ImportJob> {
  return call<ImportJob>(`/api/imports/${encodeURIComponent(id)}`);
}

export function ask(repository: string, question: string): Promise<Answer> {
  return call<Answer>("/api/ask", {
    method: "POST",
    body: JSON.stringify({ repository, question }),
  });
}

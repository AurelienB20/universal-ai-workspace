// Browser-side calls. They go to this app's Route Handlers (/api/...), which
// forward them to the backend with the API key (see lib/backend.ts).

import { readEvents } from "./sse";
import type {
  Answer,
  ImportJob,
  InterfaceConfig,
  RepositorySummary,
  SourcesFound,
  Suggestions,
} from "./types";

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
  if (!response.ok) throw await apiError(response);
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

export interface StreamHandlers {
  /** The passages the answer is written from, before any text. */
  onSources(sources: SourcesFound): void;
  /** More draft text. Unchecked: the answer returned at the end replaces it. */
  onDelta(text: string): void;
  /** The draft so far is void (the model was replaced mid-answer). */
  onReset(): void;
}

/**
 * Ask a question and follow the answer while it is written. Resolves with the checked
 * answer; rejects with an ApiError, or with the abort error when ``signal`` aborts.
 */
export async function askStream(
  repository: string,
  question: string,
  handlers: StreamHandlers,
  signal?: AbortSignal,
  fetchImpl: typeof fetch = fetch,
): Promise<Answer> {
  let response: Response;
  try {
    response = await fetchImpl("/api/ask/stream", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ repository, question }),
      signal,
    });
  } catch (caught) {
    if (signal?.aborted) throw caught;
    throw new ApiError(0, null, null);
  }
  if (!response.ok || !response.body) throw await apiError(response);

  // From here, a failure cuts an answer already under way.
  try {
    for await (const { event, data } of readEvents(response.body)) {
      if (event === "sources") handlers.onSources(JSON.parse(data) as SourcesFound);
      else if (event === "delta") handlers.onDelta((JSON.parse(data) as { text: string }).text);
      else if (event === "reset") handlers.onReset();
      else if (event === "done") return JSON.parse(data) as Answer;
      else if (event === "error") {
        const error = JSON.parse(data) as { status: number; detail: string };
        throw new ApiError(error.status, error.detail, null);
      }
    }
  } catch (caught) {
    if (caught instanceof ApiError || signal?.aborted) throw caught;
    throw new ApiError(0, STREAM_INTERRUPTED, null);
  }
  throw new ApiError(0, STREAM_INTERRUPTED, null);
}

/** Detail of the error raised when a streamed answer stops before its end. */
export const STREAM_INTERRUPTED = "The connection closed before the answer was complete.";

async function apiError(response: Response): Promise<ApiError> {
  const retryAfter = Number(response.headers.get("retry-after"));
  return new ApiError(
    response.status,
    await readDetail(response),
    Number.isFinite(retryAfter) && retryAfter > 0 ? retryAfter : null,
  );
}

export function getConfig(): Promise<InterfaceConfig> {
  return call<InterfaceConfig>("/api/config");
}

export function listRepositories(): Promise<RepositorySummary[]> {
  return call<RepositorySummary[]>("/api/repositories");
}

export function getSuggestions(repository: string, language: string): Promise<Suggestions> {
  const [owner, name] = repository.split("/").map(encodeURIComponent);
  return call<Suggestions>(
    `/api/repositories/${owner}/${name}/suggestions?language=${encodeURIComponent(language)}`,
  );
}

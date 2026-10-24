import { ApiError } from "@/lib/api";

import type { Messages } from "./messages";

/** A user-facing message, in the current language, for a failed API call. */
export function errorMessage(error: unknown, t: Messages, action: "import" | "ask"): string {
  if (!(error instanceof ApiError)) return t.errors.unexpected(0);
  switch (error.status) {
    case 0:
      return t.errors.network;
    case 401:
      return t.errors.unauthorized;
    case 403:
      return t.errors.forbidden;
    case 404:
      return t.errors.notIndexed;
    case 409:
      return t.errors.reimport;
    case 413:
      return t.errors.tooLarge;
    case 422:
      return action === "import" ? t.errors.invalidUrl : t.errors.refused;
    case 429:
      return t.errors.tooMany(
        error.retryAfterSeconds === null ? null : t.duration(error.retryAfterSeconds),
      );
    case 502:
      return t.errors.backendDown;
    case 503:
      // With Retry-After: every answer slot is taken, it frees up within seconds.
      return error.retryAfterSeconds === null
        ? t.errors.unavailable
        : t.errors.busy(t.duration(error.retryAfterSeconds));
    default:
      return t.errors.unexpected(error.status);
  }
}

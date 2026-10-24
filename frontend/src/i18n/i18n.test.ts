import { describe, expect, it } from "vitest";

import { ApiError } from "@/lib/api";

import { errorMessage } from "./errors";
import { LANGUAGES, messages } from "./messages";

function keys(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, item]) =>
    typeof item === "object" && item !== null
      ? keys(item as object, `${prefix}${key}.`)
      : [`${prefix}${key}`],
  );
}

describe("messages", () => {
  it("has the same keys in every language", () => {
    const reference = keys(messages.fr).sort();
    for (const language of LANGUAGES) {
      expect(keys(messages[language]).sort()).toEqual(reference);
    }
  });

  it("formats durations", () => {
    expect(messages.fr.duration(45)).toBe("45 s");
    expect(messages.fr.duration(90)).toBe("2 min");
    expect(messages.en.duration(7201)).toBe("3 h");
  });
});

describe("errorMessage", () => {
  it("tells when to retry after a 429", () => {
    expect(errorMessage(new ApiError(429, "limit", 120), messages.fr, "ask")).toBe(
      "Trop de requêtes, ou budget quotidien atteint. Réessayez dans 2 min.",
    );
  });

  it("explains a 422 according to the action", () => {
    const error = new ApiError(422, "bad", null);

    expect(errorMessage(error, messages.en, "import")).toMatch(/^Invalid URL/);
    expect(errorMessage(error, messages.en, "ask")).toBe("The question could not be processed.");
  });

  it("tells a demo visitor that an action is not available", () => {
    expect(errorMessage(new ApiError(403, "no", null), messages.en, "import")).toBe(
      "This action is not available on this demo.",
    );
  });

  it("tells a busy server from an unavailable one", () => {
    expect(errorMessage(new ApiError(503, "busy", 5), messages.fr, "ask")).toBe(
      "Le serveur répond déjà à d'autres questions. Réessayez dans 5 s.",
    );
    expect(errorMessage(new ApiError(503, "down", null), messages.en, "ask")).toMatch(
      /^Service unavailable/,
    );
  });

  it("covers network failures and unknown errors", () => {
    expect(errorMessage(new ApiError(0, null, null), messages.en, "ask")).toBe(
      "Cannot reach the interface server.",
    );
    expect(errorMessage(new Error("bug"), messages.en, "ask")).toBe("Unexpected error (HTTP 0).");
  });
});

import { describe, expect, it, vi } from "vitest";

import {
  type BackendConfig,
  MAX_BODY_BYTES,
  clientAddress,
  forward,
  importsEnabled,
  suggestionsPath,
} from "./backend";

const CONFIG: BackendConfig = { url: "http://backend:8000", apiKey: "server-key" };

function backendReturning(response: Response) {
  return vi.fn<typeof fetch>(async () => response);
}

function post(body: string, headers: Record<string, string> = {}): Request {
  return new Request("http://front/api/ask", { method: "POST", body, headers });
}

describe("forward", () => {
  it("adds the API key and forwards the client address", async () => {
    const fetchImpl = backendReturning(Response.json({ ok: true }));

    await forward(post('{"q": 1}', { "x-forwarded-for": "203.0.113.7" }), "/ask", CONFIG, fetchImpl);

    const [url, init] = fetchImpl.mock.calls[0];
    const headers = new Headers(init?.headers);
    expect(url).toBe("http://backend:8000/ask");
    expect(init?.method).toBe("POST");
    expect(init?.body).toBe('{"q": 1}');
    expect(headers.get("x-api-key")).toBe("server-key");
    expect(headers.get("x-forwarded-for")).toBe("203.0.113.7");
  });

  it("does not forward the browser's other headers", async () => {
    const fetchImpl = backendReturning(Response.json({}));

    await forward(post("{}", { cookie: "session=1", "x-api-key": "forged" }), "/ask", CONFIG, fetchImpl);

    const headers = new Headers(fetchImpl.mock.calls[0][1]?.headers);
    expect(headers.get("cookie")).toBeNull();
    expect(headers.get("x-api-key")).toBe("server-key");
  });

  it("sends no key when none is configured", async () => {
    const fetchImpl = backendReturning(Response.json({}));

    await forward(post("{}"), "/ask", { url: CONFIG.url, apiKey: undefined }, fetchImpl);

    expect(new Headers(fetchImpl.mock.calls[0][1]?.headers).has("x-api-key")).toBe(false);
  });

  it("returns the backend status, body and retry headers", async () => {
    const fetchImpl = backendReturning(
      Response.json(
        { detail: "Too many requests. Try again later." },
        { status: 429, headers: { "retry-after": "30", "x-request-id": "abc", server: "uvicorn" } },
      ),
    );

    const response = await forward(post("{}"), "/ask", CONFIG, fetchImpl);

    expect(response.status).toBe(429);
    expect(response.headers.get("retry-after")).toBe("30");
    expect(response.headers.get("x-request-id")).toBe("abc");
    expect(response.headers.get("server")).toBeNull();
    expect(await response.json()).toEqual({ detail: "Too many requests. Try again later." });
  });

  it("rejects an oversized body without calling the backend", async () => {
    const fetchImpl = backendReturning(Response.json({}));

    const response = await forward(post("x".repeat(MAX_BODY_BYTES + 1)), "/ask", CONFIG, fetchImpl);

    expect(response.status).toBe(413);
    expect(fetchImpl).not.toHaveBeenCalled();
  });

  it("reports an unreachable backend as 502", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });

    const response = await forward(post("{}"), "/ask", CONFIG, fetchImpl);

    expect(response.status).toBe(502);
  });
});

describe("clientAddress", () => {
  it("is the address added by the nearest proxy", () => {
    const headers = new Headers({ "x-forwarded-for": "10.0.0.1, 198.51.100.2 , 203.0.113.7" });

    expect(clientAddress(headers)).toBe("203.0.113.7");
  });

  it("is undefined without the header", () => {
    expect(clientAddress(new Headers())).toBeUndefined();
  });
});

describe("importsEnabled", () => {
  it("is on unless explicitly disabled", () => {
    expect(importsEnabled({})).toBe(true);
    expect(importsEnabled({ IMPORTS_ENABLED: "true" })).toBe(true);
    expect(importsEnabled({ IMPORTS_ENABLED: " FALSE " })).toBe(false);
  });
});

describe("suggestionsPath", () => {
  it("builds the backend path for a valid repository and language", () => {
    expect(suggestionsPath("pallets", "its.dangerous", "fr")).toBe(
      "/repositories/pallets/its.dangerous/suggestions?language=fr",
    );
  });

  it.each([
    ["-bad", "repo", "fr"],
    ["owner", "..", "fr"],
    ["owner", "a/b", "en"],
    ["owner", "repo?x=1", "en"],
    ["owner", "repo", "de"],
    ["owner", "repo", null],
  ])("rejects %s/%s in %s", (owner, name, language) => {
    expect(suggestionsPath(owner, name, language)).toBeNull();
  });
});

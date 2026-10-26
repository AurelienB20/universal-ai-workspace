import { describe, expect, it, vi } from "vitest";

import {
  type BackendConfig,
  MAX_BODY_BYTES,
  clientAddress,
  forward,
  forwardStream,
  importsEnabled,
  publicImports,
  suggestionsPath,
  visitorId,
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

describe("forwardStream", () => {
  function eventStream(chunks: string[]): ReadableStream<Uint8Array> {
    const encoder = new TextEncoder();
    return new ReadableStream({
      start(controller) {
        for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
        controller.close();
      },
    });
  }

  it("passes the events on unbuffered, with the key and the client's abort signal", async () => {
    const events = "event: sources\ndata: {}\n\nevent: done\ndata: {}\n\n";
    const body = eventStream([events.slice(0, 20), events.slice(20)]);
    const fetchImpl = backendReturning(
      new Response(body, {
        headers: { "content-type": "text/event-stream", "x-request-id": "abc" },
      }),
    );
    const browser = new AbortController();
    const request = new Request("http://front/api/ask/stream", {
      method: "POST",
      body: "{}",
      signal: browser.signal,
    });

    const response = await forwardStream(request, "/ask/stream", CONFIG, fetchImpl);

    // The backend's body itself, not a copy read to the end.
    expect(response.body).toBe(body);
    expect(response.headers.get("content-type")).toBe("text/event-stream");
    expect(response.headers.get("cache-control")).toBe("no-cache, no-transform");
    expect(response.headers.get("x-request-id")).toBe("abc");
    expect(await response.text()).toBe(events);

    const init = fetchImpl.mock.calls[0][1];
    expect(new Headers(init?.headers).get("x-api-key")).toBe("server-key");
    expect(new Headers(init?.headers).get("accept")).toBe("text/event-stream");
    // Leaving the page aborts the backend request, which stops the answer.
    expect(init?.signal?.aborted).toBe(false);
    browser.abort();
    expect(init?.signal?.aborted).toBe(true);
  });

  it("returns errors found before the stream as JSON", async () => {
    const fetchImpl = backendReturning(
      Response.json({ detail: "Busy." }, { status: 503, headers: { "retry-after": "5" } }),
    );

    const response = await forwardStream(post("{}"), "/ask/stream", CONFIG, fetchImpl);

    expect(response.status).toBe(503);
    expect(response.headers.get("retry-after")).toBe("5");
    expect(await response.json()).toEqual({ detail: "Busy." });
  });

  it("reports an unreachable backend as 502", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });

    expect((await forwardStream(post("{}"), "/ask/stream", CONFIG, fetchImpl)).status).toBe(502);
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

describe("visitor identifier", () => {
  const ID = "8f14e45f-ceea-467f-a0e6-2c6c1b0f5a3b";

  it("forwards the visitor's identifier and keeps their cookie", async () => {
    const fetchImpl = backendReturning(Response.json({}));

    const response = await forward(
      post("{}", { cookie: `theme=dark; uaw_visitor=${ID.toUpperCase()}` }),
      "/ask",
      CONFIG,
      fetchImpl,
    );

    expect(new Headers(fetchImpl.mock.calls[0][1]?.headers).get("x-visitor-id")).toBe(ID);
    expect(response.headers.get("set-cookie")).toBeNull();
  });

  it("gives a new visitor a random identifier, in an HttpOnly cookie", async () => {
    const fetchImpl = backendReturning(Response.json({}));

    const response = await forward(post("{}"), "/ask", CONFIG, fetchImpl);

    const sent = new Headers(fetchImpl.mock.calls[0][1]?.headers).get("x-visitor-id");
    expect(sent).toMatch(/^[0-9a-f-]{36}$/);
    const cookie = response.headers.get("set-cookie") ?? "";
    expect(cookie).toContain(`uaw_visitor=${sent};`);
    expect(cookie).toContain("HttpOnly");
    expect(cookie).toContain("Secure");
    expect(cookie).toContain("SameSite=Lax");
  });

  it("replaces a malformed identifier", async () => {
    const fetchImpl = backendReturning(Response.json({}));

    const response = await forwardStream(
      post("{}", { cookie: "uaw_visitor=../../admin" }),
      "/ask/stream",
      CONFIG,
      fetchImpl,
    );

    const sent = new Headers(fetchImpl.mock.calls[0][1]?.headers).get("x-visitor-id");
    expect(sent).toMatch(/^[0-9a-f-]{36}$/);
    expect(response.headers.get("set-cookie")).toContain(`uaw_visitor=${sent};`);
  });

  it("reads only its own cookie", () => {
    expect(visitorId(new Headers({ cookie: `other_uaw_visitor=${ID}` }))).toBeNull();
    expect(visitorId(new Headers())).toBeNull();
  });
});

describe("publicImports", () => {
  it("is off unless explicitly enabled", () => {
    expect(publicImports({})).toBe(false);
    expect(publicImports({ PUBLIC_IMPORTS_ENABLED: " TRUE " })).toBe(true);
    expect(publicImports({ PUBLIC_IMPORTS_ENABLED: "false" })).toBe(false);
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

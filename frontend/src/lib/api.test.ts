import { describe, expect, it, vi } from "vitest";

import { ApiError, STREAM_INTERRUPTED, askStream, type StreamHandlers } from "./api";

const SOURCES = { repository: "o/r", commit_sha: "a".repeat(40), passages: [] };
const ANSWER = {
  repository: "o/r",
  commit_sha: "a".repeat(40),
  answer: "Signed [S1].",
  insufficient_context: false,
  citations: [],
  model: "m",
};

function sse(...events: [string, unknown][]): string {
  return events.map(([name, data]) => `event: ${name}\ndata: ${JSON.stringify(data)}\n\n`).join("");
}

function streamed(text: string): typeof fetch {
  return vi.fn<typeof fetch>(
    async () => new Response(text, { headers: { "content-type": "text/event-stream" } }),
  );
}

function recorder() {
  const calls: string[] = [];
  const handlers: StreamHandlers = {
    onSources: (sources) => calls.push(`sources:${sources.passages.length}`),
    onDelta: (text) => calls.push(`delta:${text}`),
    onReset: () => calls.push("reset"),
  };
  return { calls, handlers };
}

describe("askStream", () => {
  it("follows the events, then resolves with the checked answer", async () => {
    const fetchImpl = streamed(
      sse(
        ["sources", SOURCES],
        ["delta", { text: "Draft" }],
        ["reset", {}],
        ["delta", { text: "Signed " }],
        ["delta", { text: "[S1] [S9]." }],
        ["done", ANSWER],
      ),
    );
    const { calls, handlers } = recorder();

    const answer = await askStream("o/r", "How?", handlers, undefined, fetchImpl);

    expect(answer).toEqual(ANSWER);
    expect(calls).toEqual(["sources:0", "delta:Draft", "reset", "delta:Signed ", "delta:[S1] [S9]."]);
    const [url, init] = vi.mocked(fetchImpl).mock.calls[0];
    expect(url).toBe("/api/ask/stream");
    expect(JSON.parse(init?.body as string)).toEqual({ repository: "o/r", question: "How?" });
  });

  it("rejects with the error sent during the answer", async () => {
    const fetchImpl = streamed(
      sse(["sources", SOURCES], ["error", { status: 503, detail: "Claude is unavailable." }]),
    );

    await expect(askStream("o/r", "How?", recorder().handlers, undefined, fetchImpl)).rejects.toEqual(
      new ApiError(503, "Claude is unavailable.", null),
    );
  });

  it("reports an answer cut before its end", async () => {
    const fetchImpl = streamed(sse(["sources", SOURCES], ["delta", { text: "Half" }]));

    const error = await askStream("o/r", "How?", recorder().handlers, undefined, fetchImpl).catch(
      (caught: unknown) => caught,
    );

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).detail).toBe(STREAM_INTERRUPTED);
  });

  it("rejects HTTP errors before the stream with their detail and Retry-After", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () =>
      Response.json(
        { detail: "The server is busy." },
        { status: 503, headers: { "retry-after": "5" } },
      ),
    );

    await expect(askStream("o/r", "How?", recorder().handlers, undefined, fetchImpl)).rejects.toEqual(
      new ApiError(503, "The server is busy.", 5),
    );
  });

  it("reports a network failure as such", async () => {
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      throw new TypeError("fetch failed");
    });

    const error = (await askStream("o/r", "How?", recorder().handlers, undefined, fetchImpl).catch(
      (caught: unknown) => caught,
    )) as ApiError;

    expect([error.status, error.detail]).toEqual([0, null]);
  });

  it("lets an abort through, for the caller to ignore", async () => {
    const controller = new AbortController();
    const fetchImpl = vi.fn<typeof fetch>(async () => {
      controller.abort();
      throw new DOMException("The operation was aborted.", "AbortError");
    });

    const error = await askStream("o/r", "How?", recorder().handlers, controller.signal, fetchImpl).catch(
      (caught: unknown) => caught,
    );

    expect(error).not.toBeInstanceOf(ApiError);
  });
});

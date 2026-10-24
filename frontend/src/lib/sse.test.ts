import { describe, expect, it } from "vitest";

import { EventParser, readEvents } from "./sse";

const STREAM =
  'event: sources\ndata: {"passages": []}\n\n' +
  'event: delta\ndata: {"text": "Signé [S1]"}\n\n' +
  ": a comment\n\n" +
  'event: done\ndata: {"answer": "Signé [S1]"}\n\n';

const EXPECTED = [
  { event: "sources", data: '{"passages": []}' },
  { event: "delta", data: '{"text": "Signé [S1]"}' },
  { event: "done", data: '{"answer": "Signé [S1]"}' },
];

function bodyOf(chunks: Uint8Array[]): ReadableStream<Uint8Array> {
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(chunk);
      controller.close();
    },
  });
}

async function collect(body: ReadableStream<Uint8Array>) {
  const events = [];
  for await (const event of readEvents(body)) events.push(event);
  return events;
}

describe("EventParser", () => {
  it("reads several events from one chunk", () => {
    expect(new EventParser().feed(STREAM)).toEqual(EXPECTED);
  });

  it("gives the same events wherever the text is cut", () => {
    for (let cut = 0; cut <= STREAM.length; cut++) {
      const parser = new EventParser();
      expect([...parser.feed(STREAM.slice(0, cut)), ...parser.feed(STREAM.slice(cut))]).toEqual(
        EXPECTED,
      );
    }
  });

  it("keeps an incomplete event until it ends", () => {
    const parser = new EventParser();

    expect(parser.feed("event: delta\ndata: {}")).toEqual([]);
    expect(parser.feed("\n\n")).toEqual([{ event: "delta", data: "{}" }]);
  });

  it("joins data lines and defaults the event name", () => {
    expect(new EventParser().feed("data: a\ndata: b\n\n")).toEqual([
      { event: "message", data: "a\nb" },
    ]);
  });
});

describe("readEvents", () => {
  it("decodes characters cut between two chunks", async () => {
    const bytes = new TextEncoder().encode(STREAM);
    // "é" is two bytes in UTF-8: every split point, including the middle of one.
    for (let cut = 0; cut <= bytes.length; cut += 1) {
      expect(await collect(bodyOf([bytes.slice(0, cut), bytes.slice(cut)]))).toEqual(EXPECTED);
    }
  });
});

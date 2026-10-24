// Server-sent events, read from a fetch() body: EventSource cannot send a POST.

export interface ServerEvent {
  event: string;
  data: string;
}

/**
 * Splits the text of an event stream into events. Chunks can be cut anywhere: an
 * incomplete event is kept until the rest arrives. Line breaks are "\n", as the
 * backend writes them.
 */
export class EventParser {
  private buffer = "";

  feed(chunk: string): ServerEvent[] {
    this.buffer += chunk;
    const events: ServerEvent[] = [];
    let end: number;
    while ((end = this.buffer.indexOf("\n\n")) !== -1) {
      const block = this.buffer.slice(0, end);
      this.buffer = this.buffer.slice(end + 2);
      const event = parseBlock(block);
      if (event) events.push(event);
    }
    return events;
  }
}

function parseBlock(block: string): ServerEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith(":")) continue; // a comment
    const colon = line.indexOf(":");
    const field = colon === -1 ? line : line.slice(0, colon);
    let value = colon === -1 ? "" : line.slice(colon + 1);
    if (value.startsWith(" ")) value = value.slice(1);
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  return data.length > 0 ? { event, data: data.join("\n") } : null;
}

/** The events of a response body, as they arrive. */
export async function* readEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<ServerEvent> {
  const parser = new EventParser();
  // stream: true keeps a character cut between two chunks until its last byte arrives.
  const decoder = new TextDecoder();
  const reader = body.getReader();
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) return;
      yield* parser.feed(decoder.decode(value, { stream: true }));
    }
  } finally {
    // Stops the download if the reader leaves early; harmless once it is complete.
    await reader.cancel().catch(() => undefined);
  }
}

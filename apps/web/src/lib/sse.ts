import type { AgentEvent } from "@/api/generated/types.gen";
import { ApiError, detailOf } from "./api";

/**
 * Incremental Server-Sent Events parser: feed it chunks, get back complete events.
 * Only `data:` lines are used (the API sends one JSON object per event). A blank line
 * ends an event; multi-line data is joined with newlines per the SSE spec.
 */
export class SseParser {
  private buffer = "";
  private dataLines: string[] = [];

  feed(chunk: string): string[] {
    this.buffer += chunk;
    const out: string[] = [];
    let idx: number = this.buffer.indexOf("\n");
    while (idx !== -1) {
      let line = this.buffer.slice(0, idx);
      this.buffer = this.buffer.slice(idx + 1);
      if (line.endsWith("\r")) line = line.slice(0, -1);
      if (line === "") {
        if (this.dataLines.length) {
          out.push(this.dataLines.join("\n"));
          this.dataLines = [];
        }
      } else if (line.startsWith("data:")) {
        this.dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      // comments (":...") and other fields are ignored
      idx = this.buffer.indexOf("\n");
    }
    return out;
  }

  /** Flush a trailing event with no final blank line. */
  end(): string[] {
    const rest = this.feed("\n\n");
    return rest;
  }
}

export function parseAgentEvent(data: string): AgentEvent | null {
  try {
    const obj = JSON.parse(data);
    if (obj && typeof obj === "object" && typeof obj.type === "string") return obj as AgentEvent;
  } catch {
    // ignore malformed lines
  }
  return null;
}

/**
 * POST a JSON body and stream the SSE response, calling `onEvent` for each event.
 * Resolves when the stream ends; rejects with ApiError on a non-2xx status.
 */
export async function streamSse(
  url: string,
  body: unknown,
  onEvent: (event: AgentEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json", accept: "text/event-stream" },
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    let payload: unknown = null;
    try {
      payload = await res.json();
    } catch {
      // no body
    }
    throw new ApiError(res.status, detailOf(payload, res.status));
  }
  if (!res.body) throw new ApiError(res.status, "empty stream");
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const parser = new SseParser();
  const handle = (events: string[]) => {
    for (const e of events) {
      const ev = parseAgentEvent(e);
      if (ev) onEvent(ev);
    }
  };
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    handle(parser.feed(decoder.decode(value, { stream: true })));
  }
  handle(parser.end());
}

import { describe, expect, it } from "vitest";
import { parseAgentEvent, SseParser } from "../sse";
import { applyEvent } from "../useSse";

describe("SseParser", () => {
  it("splits chunks into events regardless of chunk boundaries", () => {
    const p = new SseParser();
    const out = [
      ...p.feed('data: {"type":"thinking","del'),
      ...p.feed('ta":"hi"}\n\ndata: {"type":"done"}\n'),
      ...p.end(),
    ];
    expect(out).toEqual(['{"type":"thinking","delta":"hi"}', '{"type":"done"}']);
  });
  it("ignores comments and joins multi-line data, tolerating CRLF", () => {
    const p = new SseParser();
    const out = p.feed(": keep-alive\r\ndata: a\r\ndata: b\r\n\r\n");
    expect(out).toEqual(["a\nb"]);
  });
  it("parses only well-formed agent events", () => {
    expect(parseAgentEvent('{"type":"tool","name":"search_geo"}')?.name).toBe("search_geo");
    expect(parseAgentEvent("nope")).toBeNull();
    expect(parseAgentEvent('{"delta":"x"}')).toBeNull();
  });
});

describe("applyEvent", () => {
  const base = { status: "streaming" as const, feed: [], result: null, error: null };
  it("concatenates consecutive thinking deltas and records tools in order", () => {
    let s = applyEvent(base, { type: "thinking", delta: "Loo" });
    s = applyEvent(s, { type: "thinking", delta: "king" });
    s = applyEvent(s, {
      type: "tool",
      name: "search_geo",
      summary: "searched GEO",
      input: { queries: ["x"] },
    });
    s = applyEvent(s, { type: "thinking", delta: "Found" });
    expect(s.feed).toEqual([
      { kind: "thinking", text: "Looking" },
      { kind: "tool", name: "search_geo", summary: "searched GEO", input: { queries: ["x"] } },
      { kind: "thinking", text: "Found" },
    ]);
  });
  it("stores the result and finishes on done, or surfaces an error", () => {
    let s = applyEvent(base, { type: "result", data: { interpretation: "x" } });
    s = applyEvent(s, { type: "done" });
    expect(s.status).toBe("done");
    expect(s.result).toEqual({ interpretation: "x" });
    const e = applyEvent(applyEvent(base, { type: "error", message: "boom" }), { type: "done" });
    expect(e.status).toBe("error");
    expect(e.error).toBe("boom");
  });
});

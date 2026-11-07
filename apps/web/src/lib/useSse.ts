import { useCallback, useEffect, useRef, useState } from "react";
import type { AgentEvent } from "@/api/generated/types.gen";
import { errorMessage } from "./api";
import { streamSse } from "./sse";

export type FeedItem =
  | { kind: "thinking"; text: string }
  | { kind: "tool"; name: string; summary: string; input: Record<string, unknown> | null };

export type SseState<T> = {
  status: "idle" | "streaming" | "done" | "error";
  feed: FeedItem[];
  result: T | null;
  error: string | null;
};

/** Drive one agent stream: start(url, body) and read the live feed and result. */
export function useSse<T>() {
  const [state, setState] = useState<SseState<T>>({
    status: "idle",
    feed: [],
    result: null,
    error: null,
  });
  const abort = useRef<AbortController | null>(null);

  useEffect(() => () => abort.current?.abort(), []);

  const start = useCallback(async (url: string, body: unknown): Promise<T | null> => {
    abort.current?.abort();
    const ctl = new AbortController();
    abort.current = ctl;
    setState({ status: "streaming", feed: [], result: null, error: null });
    let result: T | null = null;
    try {
      await streamSse(
        url,
        body,
        (ev: AgentEvent) => {
          setState((s) => applyEvent(s, ev));
          if (ev.type === "result") result = ev.data as T;
        },
        ctl.signal,
      );
      setState((s) =>
        s.status === "streaming" ? { ...s, status: s.error ? "error" : "done" } : s,
      );
    } catch (e) {
      if (ctl.signal.aborted) return null;
      setState((s) => ({ ...s, status: "error", error: errorMessage(e) }));
    }
    return result;
  }, []);

  const reset = useCallback(() => {
    abort.current?.abort();
    setState({ status: "idle", feed: [], result: null, error: null });
  }, []);

  return { ...state, start, reset };
}

export function applyEvent<T>(s: SseState<T>, ev: AgentEvent): SseState<T> {
  switch (ev.type) {
    case "thinking": {
      const delta = ev.delta ?? "";
      const last = s.feed[s.feed.length - 1];
      if (last && last.kind === "thinking") {
        const feed = s.feed.slice(0, -1);
        feed.push({ kind: "thinking", text: last.text + delta });
        return { ...s, feed };
      }
      return { ...s, feed: [...s.feed, { kind: "thinking", text: delta }] };
    }
    case "tool":
      return {
        ...s,
        feed: [
          ...s.feed,
          {
            kind: "tool",
            name: ev.name ?? "tool",
            summary: ev.summary ?? "",
            input: (ev.input as Record<string, unknown> | null) ?? null,
          },
        ],
      };
    case "result":
      return { ...s, result: ev.data as T };
    case "error":
      return { ...s, status: "error", error: ev.message ?? "the agent failed" };
    case "done":
      return { ...s, status: s.error ? "error" : "done" };
    default:
      return s;
  }
}

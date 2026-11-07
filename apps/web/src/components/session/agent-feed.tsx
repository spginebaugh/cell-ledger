import { Loader2, Search, Wrench } from "lucide-react";
import { useEffect, useRef } from "react";
import type { FeedItem } from "@/lib/useSse";

/** The live transcript of an agent step: thinking summaries and the tools it ran. */
export function AgentFeed({
  feed,
  streaming,
  label,
}: {
  feed: FeedItem[];
  streaming: boolean;
  label: string;
}) {
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (feed.length) end.current?.scrollIntoView({ block: "nearest" });
  }, [feed]);
  return (
    <div className="rounded-lg border border-line bg-surface-2/60 p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        {streaming ? (
          <Loader2 size={15} className="animate-spin text-case" />
        ) : (
          <Search size={15} className="text-ink-3" />
        )}
        {label}
      </div>
      <ol className="mt-3 max-h-72 space-y-2 overflow-y-auto text-[13px] leading-relaxed">
        {feed.length === 0 && streaming && (
          <li className="text-ink-3">Waiting for the first thought…</li>
        )}
        {feed.map((item, i) =>
          item.kind === "thinking" ? (
            // biome-ignore lint/suspicious/noArrayIndexKey: the feed is append-only, so position is identity
            <li key={`t-${i}`} className="whitespace-pre-wrap text-ink-2">
              {item.text}
            </li>
          ) : (
            // biome-ignore lint/suspicious/noArrayIndexKey: append-only feed
            <li key={`tool-${i}`} className="flex items-start gap-2 text-ink">
              <Wrench size={13} className="mt-1 shrink-0 text-ink-3" />
              <span>
                <span className="font-medium">{item.summary || item.name}</span>
                {item.input && "queries" in item.input && Array.isArray(item.input.queries) && (
                  <span className="block text-ink-3">
                    {(item.input.queries as string[]).join(" · ")}
                  </span>
                )}
                {item.input && "gses" in item.input && Array.isArray(item.input.gses) && (
                  <span className="accession block text-ink-3">
                    {(item.input.gses as string[]).join(", ")}
                  </span>
                )}
                {item.input && "query" in item.input && typeof item.input.query === "string" && (
                  <span className="block text-ink-3">{item.input.query}</span>
                )}
              </span>
            </li>
          ),
        )}
        <div ref={end} />
      </ol>
    </div>
  );
}

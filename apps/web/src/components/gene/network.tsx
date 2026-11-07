import { useState } from "react";
import { Skeleton } from "@/components/ui/card";
import { fmtNum } from "@/lib/format";
import { useStringPartners } from "@/lib/gene/queries";
import { stringNetworkImageUrl, stringPageUrl } from "@/lib/gene/sources";
import { cn } from "@/lib/utils";

/** STRING's protein interaction neighbourhood, as the image STRING draws plus the partner list. */
export function Network({
  symbol,
  onPick,
  canPick,
}: {
  symbol: string;
  /** called with a partner's symbol when the user clicks one */
  onPick?: (symbol: string) => void;
  /** whether a partner can be picked (e.g. it is in the plot) */
  canPick?: (symbol: string) => boolean;
}) {
  const partners = useStringPartners(symbol);
  const [img, setImg] = useState<"loading" | "ready" | "error">("loading");
  const none = partners.isSuccess && partners.data.length === 0;

  return (
    <div>
      {!none && (
        <div className="relative overflow-hidden rounded-md border border-line bg-white">
          {img === "loading" && <Skeleton className="absolute inset-0 rounded-none" />}
          {img !== "error" && (
            <img
              src={stringNetworkImageUrl(symbol)}
              alt={`STRING interaction network around ${symbol}`}
              className={cn("block w-full", img === "ready" ? "opacity-100" : "opacity-0")}
              onLoad={() => setImg("ready")}
              onError={() => setImg("error")}
            />
          )}
          {img === "error" && (
            <p className="p-4 text-center text-sm text-ink-3">
              STRING has no network image for {symbol}.
            </p>
          )}
        </div>
      )}
      {partners.isPending && <Skeleton className="mt-2 h-8" />}
      {none && (
        <p className="text-sm text-ink-3">STRING lists no interaction partners for {symbol}.</p>
      )}
      {partners.data && partners.data.length > 0 && (
        <div className="mt-2">
          <div className="text-[12px] text-ink-3">
            Strongest partners (confidence 0 to 1). Click one that is in this plot to jump to it.
          </div>
          <ul className="mt-1 flex flex-wrap gap-1">
            {partners.data.map((p) => {
              const pickable = Boolean(onPick && canPick?.(p.symbol));
              return (
                <li key={p.symbol}>
                  <button
                    type="button"
                    disabled={!pickable}
                    onClick={() => onPick?.(p.symbol)}
                    className={cn(
                      "inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-[13px]",
                      pickable
                        ? "border-line-2 bg-surface hover:bg-surface-2"
                        : "border-transparent bg-surface-2 text-ink-2",
                    )}
                    title={pickable ? `Select ${p.symbol} on the volcano plot` : "Not in this plot"}
                  >
                    {p.symbol}
                    <span className="num text-ink-3">{fmtNum(p.score, 2)}</span>
                  </button>
                </li>
              );
            })}
          </ul>
        </div>
      )}
      <p className="mt-2 text-[12px] text-ink-3">
        <a href={stringPageUrl(symbol)} target="_blank" rel="noreferrer" className="underline">
          Open in STRING
        </a>
      </p>
    </div>
  );
}

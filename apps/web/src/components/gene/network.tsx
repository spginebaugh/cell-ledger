import { Maximize2, X } from "lucide-react";
import { Dialog as RD } from "radix-ui";
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
  const [big, setBig] = useState(false);
  const none = partners.isSuccess && partners.data.length === 0;
  const src = stringNetworkImageUrl(symbol);
  const alt = `STRING interaction network around ${symbol}`;

  return (
    <div>
      {!none && (
        // bleeds to the panel edges: the drawing is the widest thing in the panel
        <div className="relative -mx-5 overflow-hidden border-y border-line bg-white">
          {img === "loading" && <Skeleton className="absolute inset-0 rounded-none" />}
          {img !== "error" && (
            <button
              type="button"
              onClick={() => setBig(true)}
              aria-label="Enlarge the network"
              className="group block w-full cursor-zoom-in"
            >
              <img
                src={src}
                alt={alt}
                className={cn(
                  "block min-h-[360px] w-full object-contain",
                  img === "ready" ? "opacity-100" : "opacity-0",
                )}
                onLoad={() => setImg("ready")}
                onError={() => setImg("error")}
              />
              {img === "ready" && (
                <span className="absolute right-3 top-3 inline-flex items-center gap-1 rounded-md border border-line-2 bg-surface/90 px-2 py-1 text-[12px] font-semibold text-ink-2 shadow-sm group-hover:border-accent group-hover:text-accent-ink">
                  <Maximize2 size={13} />
                  Enlarge
                </span>
              )}
            </button>
          )}
          {img === "error" && (
            <p className="p-4 text-center text-sm text-ink-3">
              STRING has no network image for {symbol}.
            </p>
          )}
        </div>
      )}
      <RD.Root open={big} onOpenChange={setBig}>
        <RD.Portal>
          <RD.Overlay className="fixed inset-0 z-[60] bg-black/60" />
          <RD.Content
            aria-describedby={undefined}
            className="fixed left-1/2 top-1/2 z-[70] flex max-h-[94vh] w-[min(96vw,1400px)] -translate-x-1/2 -translate-y-1/2 flex-col overflow-hidden rounded-lg border border-line bg-white shadow-2xl focus:outline-none"
          >
            <div className="flex items-center justify-between gap-3 border-b border-line bg-surface px-4 py-2.5">
              <RD.Title className="text-[14px] font-semibold not-italic text-ink">
                STRING network around <span className="font-mono">{symbol}</span>
              </RD.Title>
              <RD.Close asChild>
                <button
                  type="button"
                  aria-label="Close"
                  className="inline-grid h-8 w-8 place-items-center rounded-md border border-line-2 bg-surface text-ink-2 hover:border-accent hover:text-accent-ink"
                >
                  <X size={15} />
                </button>
              </RD.Close>
            </div>
            <img
              src={src}
              alt={alt}
              className="block max-h-[calc(94vh-48px)] w-full object-contain p-2"
            />
          </RD.Content>
        </RD.Portal>
      </RD.Root>
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
                      "inline-flex h-7 items-center gap-1.5 rounded-md border px-2 font-mono text-[12px]",
                      pickable
                        ? "border-line-2 bg-surface text-ink hover:border-accent hover:text-accent-ink"
                        : "border-line bg-surface-2 text-ink-3",
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
        <a
          href={stringPageUrl(symbol)}
          target="_blank"
          rel="noreferrer"
          className="text-accent-ink no-underline hover:underline"
        >
          Open in STRING
        </a>
      </p>
    </div>
  );
}

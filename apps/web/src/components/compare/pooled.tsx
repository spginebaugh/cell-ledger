import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { termLabel } from "@/components/charts/enrichment-bars";
import { PooledVolcano } from "@/components/charts/pooled-volcano";
import { Skeleton } from "@/components/ui/card";
import { decodePooled, type PooledTable } from "@/lib/pooled";
import { fetchFileBytes } from "@/lib/queries";

export function usePooledTable(url: string | undefined) {
  return useQuery<PooledTable>({
    queryKey: ["pooled-genes", url],
    queryFn: async () => decodePooled(await fetchFileBytes(url as string)),
    enabled: Boolean(url),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

/** The pooled volcano with its thresholds. The adjusted-p threshold is the comparison's own
 * alpha; the fold-change floor is adjustable because it only decides which genes are drawn in
 * colour, not which are robust. */
export function PooledVolcanoPanel({
  table,
  alpha,
  lfc0,
  term,
  pin,
  selected,
  onSelect,
  themeKey,
}: {
  table: PooledTable;
  alpha: number;
  lfc0: number;
  term: EnrichmentTerm | null;
  pin: string[];
  selected: string | null;
  onSelect?: (symbol: string, geneId: string) => void;
  themeKey: string;
}) {
  const [lfc, setLfc] = useState(lfc0);
  const highlight = new Set(term?.lead_genes ?? []);
  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-x-6 gap-y-3 text-[12px] text-ink-2">
        <label className="grid gap-1 whitespace-nowrap">
          <span>
            |pooled log2FC| ≥ <span className="num font-medium text-ink">{lfc.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min={0}
            max={4}
            step={0.5}
            value={lfc}
            onChange={(e) => setLfc(Number(e.target.value))}
            className="m-0 h-[22px] w-[140px] accent-[var(--accent)]"
            aria-label="Pooled log2 fold change threshold"
          />
        </label>
        <span className="num">
          pooled padj &lt; <span className="font-medium text-ink">{alpha}</span>
        </span>
        {term && (
          <p className="w-full text-[12px] text-ink-3">
            Marking {highlight.size} leading genes of{" "}
            <span className="font-medium text-ink">{termLabel(term.term)}</span>
          </p>
        )}
      </div>
      <PooledVolcano
        table={table}
        alpha={alpha}
        lfc={lfc}
        highlight={highlight}
        pin={pin}
        selected={selected}
        onSelect={onSelect}
        themeKey={themeKey}
      />
    </div>
  );
}

export function PooledLoading() {
  return <Skeleton className="h-[440px] w-full" />;
}

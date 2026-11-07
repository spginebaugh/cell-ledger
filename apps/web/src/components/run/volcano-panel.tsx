import { useQuery } from "@tanstack/react-query";
import { useEffect, useMemo, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { Volcano } from "@/components/charts/volcano";
import { Input } from "@/components/ui/input";
import { fetchFileBytes } from "@/lib/queries";
import { decodeVolcano, type VolcanoTable } from "@/lib/volcano";
import { Skeleton } from "../ui/card";

export function useVolcanoTable(url: string | undefined) {
  return useQuery<VolcanoTable>({
    queryKey: ["volcano", url],
    queryFn: async () => decodeVolcano(await fetchFileBytes(url as string)),
    enabled: Boolean(url),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

export function VolcanoPanel({
  url,
  alpha0,
  lfc0,
  term,
  focus,
  onFocus,
  selected = null,
  onSelect,
  themeKey,
}: {
  url: string | undefined;
  alpha0: number;
  lfc0: number;
  term: EnrichmentTerm | null;
  focus: string | null;
  onFocus: (symbol: string | null) => void;
  selected?: string | null;
  onSelect?: (symbol: string, geneId: string) => void;
  themeKey: string;
}) {
  const q = useVolcanoTable(url);
  const [alpha, setAlpha] = useState(alpha0);
  const [lfc, setLfc] = useState(lfc0);
  const [search, setSearch] = useState(focus ?? "");
  useEffect(() => setSearch(focus ?? ""), [focus]);
  const highlight = useMemo(() => new Set(term?.lead_genes ?? []), [term]);
  const alphaSteps = [0.001, 0.01, 0.05, 0.1];
  const known = useMemo(
    () =>
      new Set(
        (q.data?.symbol ?? []).filter((s): s is string => Boolean(s)).map((s) => s.toUpperCase()),
      ),
    [q.data],
  );
  const unknown = search.trim() !== "" && q.data && !known.has(search.trim().toUpperCase());

  if (!url)
    return <p className="text-sm text-ink-2">No differential expression table for this run.</p>;
  if (q.isPending) return <Skeleton className="h-[420px]" />;
  if (q.isError)
    return (
      <p className="text-sm text-danger">
        Could not load the DE table: {(q.error as Error).message}
      </p>
    );
  const table = q.data;

  return (
    <div>
      <div className="mb-3 flex flex-wrap items-end gap-x-6 gap-y-3">
        <label className="text-[13px] text-ink-2">
          Significance: padj &lt; <span className="num font-medium text-ink">{alpha}</span>
          <input
            type="range"
            min={0}
            max={alphaSteps.length - 1}
            step={1}
            value={alphaSteps.indexOf(alpha) === -1 ? 2 : alphaSteps.indexOf(alpha)}
            onChange={(e) => setAlpha(alphaSteps[Number(e.target.value)])}
            className="mt-1 block w-44 accent-[var(--ink)]"
            aria-label="Adjusted p threshold"
          />
        </label>
        <label className="text-[13px] text-ink-2">
          Effect size: |log2FC| ≥ <span className="num font-medium text-ink">{lfc.toFixed(1)}</span>
          <input
            type="range"
            min={0}
            max={4}
            step={0.5}
            value={lfc}
            onChange={(e) => setLfc(Number(e.target.value))}
            className="mt-1 block w-44 accent-[var(--ink)]"
            aria-label="Log2 fold change threshold"
          />
        </label>
        <div className="min-w-[200px] flex-1 max-w-xs">
          <label htmlFor="gene-search" className="text-[13px] text-ink-2">
            Find a gene
          </label>
          <Input
            id="gene-search"
            placeholder="e.g. IL17A"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") onFocus(search.trim() || null);
              if (e.key === "Escape") {
                setSearch("");
                onFocus(null);
              }
            }}
            onBlur={() => onFocus(search.trim() || null)}
            className="mt-1"
            autoComplete="off"
          />
          {unknown && (
            <p className="mt-1 text-[12px] text-amber">
              {search.trim()} is not in the tested genes
            </p>
          )}
        </div>
        {term && (
          <p className="text-[13px] text-ink-2">
            Highlighting {highlight.size} leading genes of{" "}
            <span className="font-medium text-ink">
              {term.term
                .replace(/^HALLMARK_/, "")
                .replaceAll("_", " ")
                .toLowerCase()}
            </span>
          </p>
        )}
      </div>
      <Volcano
        table={table}
        alpha={alpha}
        lfc={lfc}
        highlight={highlight}
        focus={focus}
        selected={selected}
        onSelect={onSelect}
        themeKey={themeKey}
      />
    </div>
  );
}

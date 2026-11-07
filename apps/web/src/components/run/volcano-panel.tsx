import { useQuery } from "@tanstack/react-query";
import { useEffect, useId, useMemo, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { termLabel } from "@/components/charts/enrichment-bars";
import { Volcano } from "@/components/charts/volcano";
import { Input } from "@/components/ui/input";
import { fmtLfc, fmtP } from "@/lib/format";
import { fetchFileBytes } from "@/lib/queries";
import { cn } from "@/lib/utils";
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
  const highlight = useMemo(() => new Set(term?.lead_genes ?? []), [term]);
  const alphaSteps = [0.001, 0.01, 0.05, 0.1];

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
      <div className="mb-3 flex flex-wrap items-end gap-x-6 gap-y-3 text-[12px] text-ink-2">
        <label className="grid gap-1 whitespace-nowrap">
          <span>
            padj &lt; <span className="num font-medium text-ink">{alpha}</span>
          </span>
          <input
            type="range"
            min={0}
            max={alphaSteps.length - 1}
            step={1}
            value={alphaSteps.indexOf(alpha) === -1 ? 2 : alphaSteps.indexOf(alpha)}
            onChange={(e) => setAlpha(alphaSteps[Number(e.target.value)])}
            className="m-0 h-[22px] w-[140px] accent-[var(--accent)]"
            aria-label="Adjusted p threshold"
          />
        </label>
        <label className="grid gap-1 whitespace-nowrap">
          <span>
            |log2FC| ≥ <span className="num font-medium text-ink">{lfc.toFixed(2)}</span>
          </span>
          <input
            type="range"
            min={0}
            max={4}
            step={0.5}
            value={lfc}
            onChange={(e) => setLfc(Number(e.target.value))}
            className="m-0 h-[22px] w-[140px] accent-[var(--accent)]"
            aria-label="Log2 fold change threshold"
          />
        </label>
        <div className="ml-auto">
          <GeneSearch table={table} focus={focus} onFocus={onFocus} />
        </div>
        {term && (
          <p className="w-full text-[12px] text-ink-3">
            Marking {highlight.size} leading genes of{" "}
            <span className="font-medium text-ink">{termLabel(term.term)}</span>
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

const MAX_SUGGESTIONS = 8;

/** A combobox over the tested genes: type to see matching symbols (prefix matches first),
 * pick one with the mouse or arrow keys to put it on the volcano. The suggestions float over
 * the chart so the control never changes size while typing. */
function GeneSearch({
  table,
  focus,
  onFocus,
}: {
  table: VolcanoTable;
  focus: string | null;
  onFocus: (symbol: string | null) => void;
}) {
  const [search, setSearch] = useState(focus ?? "");
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const listId = useId();
  useEffect(() => setSearch(focus ?? ""), [focus]);

  // symbol -> row, upper-cased once
  const index = useMemo(() => {
    const m = new Map<string, number>();
    table.symbol.forEach((s, i) => {
      if (s && !m.has(s.toUpperCase())) m.set(s.toUpperCase(), i);
    });
    return m;
  }, [table]);
  const needle = search.trim().toUpperCase();
  const matches = useMemo(() => {
    if (!needle) return [];
    const starts: string[] = [];
    const contains: string[] = [];
    for (const sym of index.keys()) {
      if (sym.startsWith(needle)) starts.push(sym);
      else if (sym.includes(needle)) contains.push(sym);
      if (starts.length >= MAX_SUGGESTIONS) break;
    }
    starts.sort((a, b) => a.length - b.length || a.localeCompare(b));
    contains.sort((a, b) => a.length - b.length || a.localeCompare(b));
    return [...starts, ...contains].slice(0, MAX_SUGGESTIONS);
  }, [index, needle]);
  const exact = needle !== "" && index.has(needle);
  const showList = open && needle !== "" && !(exact && matches.length === 1);

  // biome-ignore lint/correctness/useExhaustiveDependencies: reset the cursor when the list changes
  useEffect(() => setActive(0), [needle]);

  const choose = (sym: string | null) => {
    const v = sym ?? (needle || null);
    setSearch(v ?? "");
    setOpen(false);
    onFocus(v);
  };

  return (
    <div className="relative grid gap-1">
      <label htmlFor="gene-search">Find a gene</label>
      <Input
        id="gene-search"
        role="combobox"
        aria-expanded={showList}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={
          showList && matches[active] ? `${listId}-${matches[active]}` : undefined
        }
        placeholder="e.g. IL17A"
        value={search}
        onChange={(e) => {
          setSearch(e.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown" && matches.length) {
            e.preventDefault();
            setOpen(true);
            setActive((a) => (a + 1) % matches.length);
          } else if (e.key === "ArrowUp" && matches.length) {
            e.preventDefault();
            setActive((a) => (a - 1 + matches.length) % matches.length);
          } else if (e.key === "Enter") {
            e.preventDefault();
            choose(showList && matches[active] ? matches[active] : null);
          } else if (e.key === "Escape") {
            if (showList) setOpen(false);
            else {
              setSearch("");
              onFocus(null);
            }
          }
        }}
        onBlur={() => {
          setOpen(false);
          onFocus(needle || null);
        }}
        className={cn(
          "h-[30px] w-[170px] bg-bg font-mono text-[13px]",
          needle && !exact && matches.length === 0 && "border-amber",
        )}
        autoComplete="off"
        spellCheck={false}
      />
      {showList && (
        <div
          id={listId}
          role="listbox"
          aria-label="Matching genes"
          className="absolute right-0 top-full z-20 mt-1 w-[260px] overflow-hidden rounded-md border border-line bg-surface py-1 shadow-md"
        >
          {matches.length === 0 && (
            <p className="px-3 py-1.5 text-[12px] text-amber">
              {search.trim()} is not in the tested genes
            </p>
          )}
          {matches.map((sym, k) => {
            const i = index.get(sym) as number;
            const lfc = table.log2fc[i];
            const p = table.padj[i];
            const shown = table.symbol[i] ?? sym;
            const at = sym.indexOf(needle);
            return (
              <div
                key={sym}
                id={`${listId}-${sym}`}
                role="option"
                tabIndex={-1}
                aria-selected={k === active}
                onMouseDown={(e) => e.preventDefault()} // keep focus so blur does not fire first
                onMouseEnter={() => setActive(k)}
                onClick={() => choose(sym)}
                onKeyDown={(e) => e.key === "Enter" && choose(sym)}
                className={cn(
                  "flex cursor-pointer items-baseline justify-between gap-3 px-3 py-1.5 text-[13px]",
                  k === active ? "bg-accent-soft text-accent-ink" : "text-ink",
                )}
              >
                <span className="font-mono font-medium">
                  {shown.slice(0, at)}
                  <mark className="bg-transparent text-inherit underline decoration-accent/60 underline-offset-2">
                    {shown.slice(at, at + needle.length)}
                  </mark>
                  {shown.slice(at + needle.length)}
                </span>
                <span className="num shrink-0 text-[12px] text-ink-3">
                  <span className={lfc > 0 ? "text-case" : "text-control"}>{fmtLfc(lfc)}</span>
                  {" · "}
                  {Number.isNaN(p) ? "padj —" : `padj ${fmtP(p)}`}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

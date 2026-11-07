import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

const fmtFdr = (f: number) => (f < 1e-3 ? "<0.001" : f.toFixed(3));

export function termLabel(term: string): string {
  return term.replace(/^HALLMARK_/, "").replaceAll("_", " ");
}

/** Pathways as a table: set, a bar centred on zero, NES and FDR; select a row to mark its genes. */
export function EnrichmentBars({
  terms,
  selected,
  onSelect,
  n = 20,
}: {
  terms: EnrichmentTerm[];
  selected: string | null;
  onSelect: (term: EnrichmentTerm | null) => void;
  n?: number;
}) {
  const shown = terms.slice(0, n);
  return (
    <div className="num grid grid-cols-[minmax(0,1fr)_80px_44px_52px] gap-x-3 text-[13px]">
      <div className="pb-2 text-[12px] text-ink-3">Set</div>
      <div className="flex justify-between pb-2 text-[12px] text-ink-3">
        <span>−4</span>
        <span>NES</span>
        <span>+4</span>
      </div>
      <div className="pb-2 text-right text-[12px] text-ink-3">NES</div>
      <div className="pb-2 text-right text-[12px] text-ink-3">FDR</div>
      {shown.map((t) => {
        const isSel = selected === t.term;
        const w = Math.min(50, (Math.abs(t.nes) / 4) * 50);
        const label = termLabel(t.term);
        return (
          <button
            key={t.term}
            type="button"
            aria-pressed={isSel}
            onClick={() => onSelect(isSel ? null : t)}
            title={`${label}: NES ${fmtNum(t.nes)}, FDR ${fmtNum(t.fdr, 3)}, ${t.size} genes`}
            className="group contents cursor-pointer"
          >
            <span
              className={cn(
                "flex h-[30px] min-w-0 items-center overflow-hidden text-ellipsis whitespace-nowrap border-t border-line text-left text-ink-2 group-hover:text-ink",
                isSel && "font-medium text-accent-ink",
              )}
            >
              {label}
            </span>
            <span className="relative flex h-[30px] items-center border-t border-line">
              <span className="absolute bottom-1.5 left-1/2 top-1.5 border-l border-line-2" />
              <span
                className={cn(
                  "absolute top-[11px] h-2",
                  t.nes < 0 ? "right-1/2 rounded-l-sm bg-control" : "left-1/2 rounded-r-sm bg-case",
                  isSel && "ring-2 ring-accent ring-offset-2 ring-offset-surface",
                )}
                style={{ width: `${w}%` }}
              />
            </span>
            <span className="flex h-[30px] items-center justify-end border-t border-line text-ink-2">
              {t.nes > 0 ? "+" : "−"}
              {Math.abs(t.nes).toFixed(2)}
            </span>
            <span className="flex h-[30px] items-center justify-end border-t border-line text-ink-3">
              {fmtFdr(t.fdr)}
            </span>
          </button>
        );
      })}
    </div>
  );
}

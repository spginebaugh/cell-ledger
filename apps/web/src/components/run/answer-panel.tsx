import { Info } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import type { AnalysisReport, GeneLookupRow } from "@/api/generated/types.gen";
import { Details, KeyValues, Notice, Panel, Tag } from "@/components/ui/card";
import {
  fmtInt,
  fmtLfc,
  fmtNum,
  fmtP,
  reasonLabel,
  statusLabel,
  verdictGlyph,
  verdictLabel,
  verdictTone,
} from "@/lib/format";
import { cn } from "@/lib/utils";

/** The warnings the pipeline raised, behind an amber info button at the notice's right edge. */
function WarningsButton({ warnings }: { warnings: string[] }) {
  const [open, setOpen] = useState(false);
  const n = warnings.length;
  if (n === 0) return null;
  const label = `${n} warning${n === 1 ? "" : "s"} from the pipeline`;
  return (
    <>
      <button
        type="button"
        aria-expanded={open}
        aria-controls="pipeline-warnings"
        aria-label={label}
        title={label}
        onClick={() => setOpen((o) => !o)}
        className={cn(
          "pill inline-flex h-7 shrink-0 items-center gap-1.5 rounded-md border border-line-2 bg-surface pl-2 pr-2.5 text-[12px] font-semibold text-amber hover:border-amber/50 hover:bg-amber-soft",
          open && "border-amber/50 bg-amber-soft",
        )}
      >
        <Info size={14} />
        {n} warning{n === 1 ? "" : "s"}
      </button>
      <ul
        id="pipeline-warnings"
        hidden={!open}
        className="mt-3 w-full list-disc border-t border-line pl-5 pt-3 text-[13px] text-ink-2 [&_li]:break-words [&_li+li]:mt-1"
      >
        {warnings.map((w) => (
          <li key={w}>{w}</li>
        ))}
      </ul>
    </>
  );
}

export function StatusBanner({
  report,
  error,
  status,
}: {
  report: AnalysisReport | null;
  error?: string | null;
  status: string;
}) {
  if (status === "failed" || (!report && error)) {
    return (
      <Notice tone="danger" title="The run failed before it could produce a result">
        {error ?? "no details were recorded"}
      </Notice>
    );
  }
  if (!report) return null;
  const blockers = report.blockers ?? [];
  const quals = report.qualifications ?? [];
  const warnings = report.warnings ?? [];
  const flags = report.qc?.flags ?? [];
  const warn = <WarningsButton warnings={warnings} />;
  if (report.status === "blocked") {
    return (
      <Notice tone="danger" title="Blocked: Not a Result" actions={warn}>
        <ul>
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
        {report.error && <p className="mt-1 break-words">Pipeline error: {report.error}</p>}
      </Notice>
    );
  }
  if (report.status === "qc_only") {
    return (
      <Notice tone="amber" title="QC Only: Differential Expression Did Not Run" actions={warn}>
        <ul>
          {blockers.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      </Notice>
    );
  }
  if (quals.length > 0) {
    return (
      <Notice tone="amber" title="Complete: Read It With These Caveats" actions={warn}>
        <ul>
          {quals.map((q) => (
            <li key={q}>{q}</li>
          ))}
        </ul>
      </Notice>
    );
  }
  return (
    <Notice tone="ok" title={`${statusLabel(report.status)}: Passed Checks`} actions={warn}>
      {report.de && (
        <p className="num">
          {fmtInt(report.de.summary.n_sig)} of {fmtInt(report.de.summary.n_genes_tested)} tested
          genes differ at padj &lt; {report.de.summary.alpha}.
        </p>
      )}
      <p>{flags.length ? `QC flags: ${flags.join(", ")}.` : "No dataset-level QC flags."}</p>
    </Notice>
  );
}

export function VerdictCard({
  row,
  onFocus,
  active,
}: {
  row: GeneLookupRow;
  onFocus?: (symbol: string) => void;
  active?: boolean;
}) {
  const tone = verdictTone(row.verdict);
  const symbol = row.symbol ?? row.query;
  const clickable = Boolean(onFocus && row.gene_id);
  const hasNumbers =
    row.verdict === "up" || row.verdict === "down" || row.verdict === "no_evidence";
  return (
    <Panel
      className={cn(
        "w-full min-w-[min(280px,100%)] flex-[0_1_340px] px-4 py-3",
        active && "border-accent",
      )}
      id={`gene-${symbol.toUpperCase()}`}
    >
      <div className="flex min-h-[30px] items-center justify-between gap-3">
        {clickable ? (
          <button
            type="button"
            onClick={() => onFocus?.(symbol)}
            title={`Find ${symbol} on the volcano`}
            aria-pressed={active}
            className="font-display text-[26px] font-medium leading-none text-ink hover:text-accent-ink"
            style={{ fontVariationSettings: '"opsz" 48' }}
          >
            {symbol}
          </button>
        ) : (
          <span
            className="font-display text-[26px] font-medium leading-none"
            style={{ fontVariationSettings: '"opsz" 48' }}
          >
            {symbol}
          </span>
        )}
        <span className="inline-flex items-center gap-3">
          <Tag tone={tone === "case" ? "case" : tone === "control" ? "control" : "muted"}>
            {verdictLabel(row.verdict)}
          </Tag>
          <span
            aria-hidden
            className={cn(
              "text-[20px] leading-none",
              tone === "case" && "text-case",
              tone === "control" && "text-control",
              tone !== "case" && tone !== "control" && "text-ink-3",
            )}
          >
            {verdictGlyph(row.verdict)}
          </span>
        </span>
      </div>
      <Details summary="Details" className="mt-2">
        {row.symbol && row.query.toUpperCase() !== row.symbol.toUpperCase() && (
          <p className="mb-2 text-[12px] text-ink-3">asked as {row.query}</p>
        )}
        {hasNumbers ? (
          <KeyValues
            rows={[
              {
                k: "log2 fold change",
                v: <span className="font-medium">{fmtLfc(row.log2fc)}</span>,
              },
              { k: "adjusted p", v: <span className="font-medium">{fmtP(row.padj)}</span> },
              { k: "mean, case", v: fmtNum(row.mean_norm_case, 1) },
              { k: "mean, control", v: fmtNum(row.mean_norm_control, 1) },
              ...(row.rank_by_padj != null
                ? [{ k: "rank by padj", v: `#${fmtInt(row.rank_by_padj)}` }]
                : []),
            ]}
          />
        ) : (
          <p>{reasonLabel(row.reason) || "no estimate for this gene"}</p>
        )}
      </Details>
    </Panel>
  );
}

/** Cards start at the left while they fit one row, and centre once they wrap. */
export function AnswerPanel({
  report,
  onFocus,
  focus,
}: {
  report: AnalysisReport;
  onFocus?: (symbol: string) => void;
  focus?: string | null;
}) {
  const rows = report.gene_lookup ?? [];
  const ref = useRef<HTMLDivElement>(null);
  const [wrapped, setWrapped] = useState(false);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    const check = () =>
      setWrapped(new Set([...el.children].map((c) => (c as HTMLElement).offsetTop)).size > 1);
    check();
    if (!("ResizeObserver" in window)) return;
    const ro = new ResizeObserver(check);
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  if (rows.length === 0) {
    return (
      <p className="text-sm text-ink-2">
        No genes were asked about for this run. The tables and figures below still describe the full
        comparison.
      </p>
    );
  }
  return (
    <div
      ref={ref}
      className={cn("flex flex-wrap gap-3", wrapped ? "justify-center" : "justify-start")}
    >
      {rows.map((r) => (
        <VerdictCard
          key={r.query}
          row={r}
          onFocus={onFocus}
          active={focus?.toUpperCase() === (r.symbol ?? r.query).toUpperCase()}
        />
      ))}
    </div>
  );
}

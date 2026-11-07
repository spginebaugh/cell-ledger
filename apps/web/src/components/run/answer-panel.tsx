import type { AnalysisReport, GeneLookupRow } from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Card, Details, Notice } from "@/components/ui/card";
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
  return (
    <div className="space-y-3">
      {report.status === "blocked" && (
        <Notice tone="danger" title="This contrast must not be read as a result">
          <ul>
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
          {report.error && <p className="mt-1 break-words">Pipeline error: {report.error}</p>}
        </Notice>
      )}
      {report.status === "qc_only" && (
        <Notice tone="amber" title="Quality control ran, but differential expression did not">
          <ul>
            {blockers.map((b) => (
              <li key={b}>{b}</li>
            ))}
          </ul>
        </Notice>
      )}
      {report.status === "complete" && quals.length > 0 && (
        <Notice tone="amber" title="The result stands, but read it with these caveats">
          <ul>
            {quals.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
        </Notice>
      )}
      {report.status === "complete" && quals.length === 0 && (
        <Notice tone="ok" title={`${statusLabel(report.status)}: the contrast passed its checks`}>
          {report.de
            ? `${fmtInt(report.de.summary.n_sig)} of ${fmtInt(report.de.summary.n_genes_tested)} tested genes differ at padj < ${report.de.summary.alpha}. `
            : ""}
          {report.qc?.flags?.length
            ? `QC flags: ${report.qc.flags.join(", ")}.`
            : "No dataset-level QC flags."}
        </Notice>
      )}
      {warnings.length > 0 && (
        <Details
          summary={`${warnings.length} warning${warnings.length === 1 ? "" : "s"} from the pipeline`}
        >
          <ul className="list-disc space-y-1 pl-5 text-sm text-ink-2 [&_li]:break-words">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        </Details>
      )}
    </div>
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
  const body = (
    <>
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-display text-[1.35rem] leading-none">{symbol}</div>
          {row.symbol && row.query.toUpperCase() !== row.symbol.toUpperCase() && (
            <div className="mt-0.5 text-[12px] text-ink-3">asked as {row.query}</div>
          )}
        </div>
        <span
          aria-hidden
          className={cn(
            "font-display text-[1.6rem] leading-none",
            tone === "case" && "text-case",
            tone === "control" && "text-control",
            tone === "muted" && "text-ink-3",
          )}
        >
          {verdictGlyph(row.verdict)}
        </span>
      </div>
      <Badge tone={tone} className="mt-2.5">
        {verdictLabel(row.verdict)}
      </Badge>
      {row.verdict === "up" || row.verdict === "down" || row.verdict === "no_evidence" ? (
        <dl className="num mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[13px]">
          <dt className="text-ink-2">log2 fold change</dt>
          <dd className="text-right font-medium">{fmtLfc(row.log2fc)}</dd>
          <dt className="text-ink-2">adjusted p</dt>
          <dd className="text-right font-medium">{fmtP(row.padj)}</dd>
          <dt className="text-ink-2">mean, case</dt>
          <dd className="text-right">{fmtNum(row.mean_norm_case, 1)}</dd>
          <dt className="text-ink-2">mean, control</dt>
          <dd className="text-right">{fmtNum(row.mean_norm_control, 1)}</dd>
          {row.rank_by_padj != null && (
            <>
              <dt className="text-ink-2">rank by padj</dt>
              <dd className="text-right">#{fmtInt(row.rank_by_padj)}</dd>
            </>
          )}
        </dl>
      ) : (
        <p className="mt-3 text-[13px] text-ink-2">
          {reasonLabel(row.reason) || "no estimate for this gene"}
        </p>
      )}
    </>
  );
  const cls = cn(
    "h-full rounded-lg border p-4 text-left transition-colors",
    active ? "border-ink" : "border-line",
    clickable && "hover:border-line-2",
  );
  return clickable ? (
    <button
      type="button"
      onClick={() => onFocus?.(symbol)}
      className={cn(cls, "bg-surface w-full")}
      style={{ boxShadow: "var(--shadow)" }}
      aria-pressed={active}
    >
      {body}
    </button>
  ) : (
    <Card className={cn(cls, "p-4")}>{body}</Card>
  );
}

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
  if (rows.length === 0) {
    return (
      <p className="text-sm text-ink-2">
        No genes were asked about for this run. The tables and figures below still describe the full
        comparison.
      </p>
    );
  }
  return (
    <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
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

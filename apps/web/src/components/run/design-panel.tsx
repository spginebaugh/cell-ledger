import type { AnalysisReport, RunRequest } from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Card, Stat } from "@/components/ui/card";
import { fmtInt, fmtNum } from "@/lib/format";

export function DesignPanel({
  report,
  design,
}: {
  report: AnalysisReport;
  design: RunRequest | null;
}) {
  const c = report.contrast;
  const de = report.de?.summary;
  const rec = report.reconciliation;
  const dropped = [
    ...(rec?.contrast_gsms_missing_from_counts ?? []),
    ...(rec?.contrast_gsms_missing_from_sheet ?? []),
  ];
  const pairing = de?.pairing ?? "none";
  return (
    <Card className="p-5">
      <div className="grid gap-5 md:grid-cols-[1fr_1fr_auto]">
        <div className="border-l-[3px] border-case pl-3">
          <div className="text-[13px] text-ink-2">Case</div>
          <div className="font-medium leading-snug">{c.case_label}</div>
          <div className="num mt-1 text-[13px] text-ink-2">
            {c.case_gsms.length} samples proposed
            {de ? `, ${de.n_case_used} fitted` : rec ? `, ${rec.n_case} with counts` : ""}
          </div>
        </div>
        <div className="border-l-[3px] border-control pl-3">
          <div className="text-[13px] text-ink-2">Control</div>
          <div className="font-medium leading-snug">{c.control_label}</div>
          <div className="num mt-1 text-[13px] text-ink-2">
            {c.control_gsms.length} samples proposed
            {de ? `, ${de.n_control_used} fitted` : rec ? `, ${rec.n_control} with counts` : ""}
          </div>
        </div>
        <div className="flex flex-wrap gap-6 md:flex-col md:gap-3">
          <Stat
            label="Design"
            value={
              <code className="font-mono text-[14px]">
                {de?.design ?? (c.blocking ? `~${c.blocking} + arm` : "~arm")}
              </code>
            }
          />
          <Stat
            label="Pairing"
            value={
              pairing === "modelled"
                ? `by ${c.blocking}`
                : pairing === "none"
                  ? "none"
                  : pairing.replaceAll("_", " ")
            }
          />
          <Stat
            label="Contrast confidence"
            value={c.confidence != null ? fmtNum(c.confidence, 2) : "n/a"}
            hint={
              <Badge
                tone={
                  c.status === "confirmed" ? "ok" : c.status === "uncertain" ? "amber" : "neutral"
                }
              >
                {c.status}
              </Badge>
            }
          />
        </div>
      </div>
      {c.rationale && <p className="mt-4 max-w-[80ch] text-sm text-ink-2">{c.rationale}</p>}
      {rec && (
        <p className="num mt-3 text-[13px] text-ink-3">
          Counts matrix: {fmtInt(rec.n_genes)} genes × {fmtInt(rec.n_counts_columns)} columns;{" "}
          {rec.gsms_used.length} contrast samples matched.
          {dropped.length > 0 && (
            <>
              {" "}
              Dropped {dropped.length} GSM{dropped.length === 1 ? "" : "s"} without counts or sheet
              entry: <span className="accession">{dropped.join(", ")}</span>.
            </>
          )}
          {de?.collapsed && Object.keys(de.collapsed).length > 0 && (
            <>
              {" "}
              {de.n_samples_collapsed} samples were summed within {Object.keys(de.collapsed).length}{" "}
              donor/arm blocks before the fit.
            </>
          )}
        </p>
      )}
      {design?.samplesheet.title && (
        <p className="mt-1 text-[13px] text-ink-3">Series: {design.samplesheet.title}</p>
      )}
    </Card>
  );
}

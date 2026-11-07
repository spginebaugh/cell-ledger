import { format } from "d3-format";

const sci = format(".2~e");
const fixed2 = format(".2f");
const signed2 = format("+.2f");
const int = format(",d");
const pct0 = format(".0%");

export function fmtP(p: number | null | undefined): string {
  if (p === null || p === undefined || Number.isNaN(p)) return "n/a";
  if (p === 0) return "<1e-300";
  if (p < 1e-3) return sci(p).replace("e", "e");
  return fixed2(p);
}

export function fmtLfc(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return signed2(v);
}

export function fmtNum(v: number | null | undefined, digits = 2): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return format(`.${digits}f`)(v);
}

export function fmtInt(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return int(v);
}

export function fmtPct(v: number | null | undefined): string {
  if (v === null || v === undefined || Number.isNaN(v)) return "n/a";
  return pct0(v);
}

export function fmtMillions(v: number): string {
  return `${format(".1f")(v / 1e6)}M`;
}

export function fmtSeconds(s: number | null | undefined): string {
  if (s === null || s === undefined) return "";
  if (s < 1) return `${Math.round(s * 1000)} ms`;
  if (s < 90) return `${format(".1f")(s)} s`;
  const m = Math.floor(s / 60);
  return `${m} min ${Math.round(s - m * 60)} s`;
}

export function elapsedSince(iso: string, now = Date.now()): number {
  return Math.max(0, (now - new Date(iso).getTime()) / 1000);
}

/** Per-dataset verdicts (AnalysisReport.gene_lookup). */
export type Verdict =
  | "up"
  | "down"
  | "no_evidence"
  | "untestable"
  | "not_tested"
  | "not_found"
  | "not_run";

export type Tone = "case" | "control" | "muted" | "danger" | "amber" | "ok" | "neutral";

export function verdictLabel(v: string): string {
  switch (v) {
    case "up":
      return "Higher in case";
    case "down":
      return "Higher in control";
    case "no_evidence":
      return "No evidence";
    case "untestable":
      return "Untestable";
    case "not_tested":
      return "Not tested";
    case "not_found":
      return "Not found";
    case "not_run":
      return "Not run";
    case "replicated_up":
      return "Replicated: higher in case";
    case "replicated_down":
      return "Replicated: higher in control";
    case "pooled_up":
      return "Pooled: higher in case";
    case "pooled_down":
      return "Pooled: higher in control";
    case "inconsistent":
      return "Inconsistent";
    case "insufficient":
      return "Insufficient data";
    default:
      return v.replaceAll("_", " ");
  }
}

export function verdictTone(v: string): Tone {
  if (v.endsWith("up")) return "case";
  if (v.endsWith("down")) return "control";
  if (v === "inconsistent") return "amber";
  return "muted";
}

export function verdictGlyph(v: string): string {
  if (v.endsWith("up")) return "▲";
  if (v.endsWith("down")) return "▼";
  if (v === "inconsistent") return "⇅";
  return "–";
}

export function reasonLabel(reason: string | null | undefined): string {
  switch (reason) {
    case "independent_filtering":
      return "DESeq2 reported no adjusted p (independent filtering: too few counts to test)";
    case "outlier_or_all_zero":
      return "flagged as an outlier or all counts were zero";
    case "filtered_before_testing":
      return "removed by the low-count filter before testing";
    case "symbol_not_in_annotation":
      return "symbol not in the NCBI annotation";
    case "de_not_run":
      return "differential expression did not run";
    default:
      return reason ?? "";
  }
}

export type RunStateName = "running" | "complete" | "qc_only" | "blocked" | "failed";

export function statusLabel(s: string): string {
  switch (s) {
    case "running":
      return "Running";
    case "complete":
      return "Complete";
    case "qc_only":
      return "QC only";
    case "blocked":
      return "Blocked";
    case "failed":
      return "Failed";
    case "insufficient":
      return "Insufficient";
    case "pending":
      return "Downloading";
    case "ready":
      return "Ready";
    case "excluded":
      return "Excluded";
    default:
      return s;
  }
}

export function statusTone(s: string): Tone {
  switch (s) {
    case "complete":
    case "ready":
      return "ok";
    case "running":
    case "pending":
      return "neutral";
    case "qc_only":
    case "insufficient":
      return "amber";
    case "blocked":
    case "failed":
    case "excluded":
      return "danger";
    default:
      return "neutral";
  }
}

export function stepLabel(name: string): string {
  switch (name) {
    case "load":
      return "Load counts and reconcile samples";
    case "qc":
      return "Quality control";
    case "filter_genes":
      return "Filter low-count genes";
    case "deseq2":
      return "DESeq2 differential expression";
    case "gsea_prerank":
      return "Gene set enrichment (GSEA)";
    case "gene_lookup":
      return "Look up genes of interest";
    case "figures":
      return "Draw figures";
    default:
      return name.replaceAll("_", " ");
  }
}

export const PIPELINE_STEPS = [
  "load",
  "qc",
  "filter_genes",
  "deseq2",
  "gsea_prerank",
  "gene_lookup",
  "figures",
];

export function humanExclusion(e: string): string {
  switch (e) {
    case "no_ncbi_counts":
      return "NCBI has not generated raw counts for this series";
    case "counts_not_integer":
      return "the counts matrix is not integer counts";
    case "no_eligible_samples":
      return "no human bulk RNA-seq sample has counts";
    default:
      return e.replaceAll("_", " ");
  }
}

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { AnalysisReport } from "@/api/generated/types.gen";
import { AnswerPanel, StatusBanner } from "../answer-panel";

const report: AnalysisReport = {
  gse: "GSE1",
  contrast: {
    gse: "GSE1",
    name: "a_vs_b",
    case_label: "lesional skin",
    control_label: "healthy skin",
    case_gsms: ["GSM1", "GSM2", "GSM3"],
    control_gsms: ["GSM4", "GSM5", "GSM6"],
    status: "confirmed",
  },
  status: "complete",
  blockers: [],
  qualifications: ["contrast confidence 0.60 < 0.7"],
  warnings: ["3 counts columns are not in the sample sheet and were ignored"],
  created_at: "2026-11-07T00:00:00Z",
  versions: { pydeseq2: "0.5" },
  params: {},
  steps: [],
  gene_lookup: [
    {
      query: "IL17A",
      gene_id: "3605",
      symbol: "IL17A",
      verdict: "up",
      log2fc: 4.2,
      padj: 1.3e-9,
      mean_norm_case: 120.4,
      mean_norm_control: 3.1,
      rank_by_padj: 12,
    },
    { query: "FLG", gene_id: "2312", symbol: "FLG", verdict: "down", log2fc: -2.1, padj: 0.0004 },
    {
      query: "NOPE",
      gene_id: null,
      symbol: null,
      verdict: "not_found",
      reason: "symbol_not_in_annotation",
    },
  ],
  gene_expression: [],
  files: {},
  figures: {},
  de: {
    summary: {
      design: "~arm",
      coefficient: "arm",
      n_case_used: 3,
      n_control_used: 3,
      lfc_shrunk: true,
      alpha: 0.05,
      lfc_threshold: 1,
      n_genes_tested: 1000,
      n_sig: 100,
      n_up: 60,
      n_down: 40,
      n_up_lfc: 30,
      n_down_lfc: 20,
    },
    top_up: [],
    top_down: [],
  },
};

describe("AnswerPanel", () => {
  it("renders one verdict card per gene with its numbers and reasons", () => {
    render(<AnswerPanel report={report} />);
    expect(screen.getByText("IL17A")).toBeInTheDocument();
    expect(screen.getByText("Higher in case")).toBeInTheDocument();
    expect(screen.getByText("+4.20")).toBeInTheDocument();
    expect(screen.getByText("1.3e-9")).toBeInTheDocument();
    expect(screen.getByText("#12")).toBeInTheDocument();
    expect(screen.getByText("Higher in control")).toBeInTheDocument();
    expect(screen.getByText("Not found")).toBeInTheDocument();
    expect(screen.getByText(/not in the NCBI annotation/)).toBeInTheDocument();
  });
  it("shows qualifications as caveats and collapses warnings", () => {
    render(<StatusBanner report={report} status="complete" />);
    expect(screen.getByText(/read it with these caveats/)).toBeInTheDocument();
    expect(screen.getByText("contrast confidence 0.60 < 0.7")).toBeInTheDocument();
    expect(screen.getByText("1 warning from the pipeline")).toBeInTheDocument();
  });
  it("explains a blocked run in plain terms", () => {
    render(
      <StatusBanner
        report={{
          ...report,
          status: "blocked",
          blockers: ["fewer than 3 samples per group (2 case, 3 control)"],
        }}
        status="blocked"
      />,
    );
    expect(screen.getByText(/must not be read as a result/)).toBeInTheDocument();
    expect(screen.getByText(/fewer than 3 samples/)).toBeInTheDocument();
  });
});

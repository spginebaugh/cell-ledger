import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  EnrichmentTerm,
  GeneMeta,
  PathwaySynthesis,
  QcResult,
} from "@/api/generated/types.gen";
import { armPurity, fromRawHeatmap } from "@/lib/heatmap";
import { ExpressionHeatmap } from "../expression-heatmap";
import { PathwayMatrix } from "../pathway-matrix";
import { PathwayNetwork } from "../pathway-network";
import { PcaScatter } from "../pca";
import { hasPerMemberEffects, ReplicationStrip } from "../replication-strip";

const W = 700;

beforeEach(() => {
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get: () => W,
  });
  HTMLCanvasElement.prototype.getContext = (() => null) as never;
});
afterEach(() => vi.unstubAllGlobals());

const qc: QcResult = {
  samples: [
    {
      gsm: "GSM1",
      arm: "case",
      library_size: 2e7,
      detected_genes: 20000,
      pct_mito: 1,
      pct_ribo: 5,
      flags: [],
    },
    {
      gsm: "GSM2",
      arm: "case",
      library_size: 2e7,
      detected_genes: 20000,
      pct_mito: 1,
      pct_ribo: 5,
      flags: ["low_library_size"],
    },
    {
      gsm: "GSM3",
      arm: "control",
      library_size: 2e7,
      detected_genes: 20000,
      pct_mito: 1,
      pct_ribo: 5,
    },
  ],
  median_library_size: 2e7,
  pca: {
    n_genes_used: 2000,
    variance_ratio: [0.6, 0.2],
    coords: { GSM1: [10, 1], GSM2: [9, -1], GSM3: [-12, 0] },
    arm_r2_pc1: 0.94,
  },
  flags: [],
  params: {},
};

describe("PcaScatter", () => {
  it("draws one point per sample and names the arm on hover", () => {
    const { getAllByRole, getByLabelText, getByText } = render(
      <PcaScatter qc={qc} caseLabel="lesional" controlLabel="healthy" />,
    );
    expect(getAllByRole("graphics-symbol")).toHaveLength(3);
    fireEvent.mouseMove(getByLabelText("GSM1 (case)"), { clientX: 100, clientY: 100 });
    expect(getByText("GSM1")).toBeInTheDocument();
    expect(getByText("lesional")).toBeInTheDocument();
    expect(getByText(/arm explains 94% of PC1/)).toBeInTheDocument();
    expect(getByText(/1 with a QC flag/)).toBeInTheDocument();
  });
});

describe("ExpressionHeatmap", () => {
  const table = fromRawHeatmap({
    n_genes: 2,
    n_samples: 4,
    alpha: 0.05,
    lfc_threshold: 1,
    genes: [
      { gene_id: "1", symbol: "UP1", log2fc: 2, padj: 1e-5 },
      { gene_id: "2", symbol: null, log2fc: -2, padj: 1e-4 },
    ],
    samples: [
      { id: "A", arm: "case" },
      { id: "B", arm: "control" },
      { id: "C", arm: "case" },
      { id: "D", arm: "control" },
    ],
    row_order: [1, 0],
    col_order: [0, 2, 1, 3],
    z: [
      [1, -1, 1, -1],
      [-1, 1, -1, 1],
    ],
    log2: [
      [8, 6, 8, 6],
      [6, 8, 6, 8],
    ],
  });

  it("reports how cleanly samples sort into their arms", () => {
    expect(armPurity(table)).toBeCloseTo(2 / 3);
  });

  it("labels rows in clustered order and opens a gene from its label", () => {
    const onSelect = vi.fn();
    const { getByText, queryByText } = render(
      <ExpressionHeatmap
        table={table}
        caseLabel="case"
        controlLabel="control"
        onSelect={onSelect}
      />,
    );
    fireEvent.click(getByText("UP1"));
    expect(onSelect).toHaveBeenCalledWith("UP1", "1");
    // a gene without a symbol shows its id and cannot be opened
    fireEvent.click(getByText("2"));
    expect(onSelect).toHaveBeenCalledTimes(1);
    expect(queryByText(/sort into their arms/)).not.toBeInTheDocument(); // too few samples to quote
  });
});

const members = ["GSE1:a", "GSE2:b", "GSE3:c"];

describe("PathwayMatrix", () => {
  const pathways: PathwaySynthesis = {
    library: "hallmark",
    members,
    fdr_threshold: 0.25,
    n_terms: 2,
    n_consistent: 1,
    terms: [
      {
        term: "HALLMARK_INTERFERON_GAMMA_RESPONSE",
        n_members: 3,
        mean_nes: 2.5,
        n_pos: 3,
        n_neg: 0,
        n_sig_fdr: 3,
        consistency: 1,
        nes: { "GSE1:a": 2.9, "GSE2:b": 2.1, "GSE3:c": 2.6 },
        fdr: { "GSE1:a": 0.001, "GSE2:b": 0.1, "GSE3:c": 0.0 },
      },
      {
        term: "HALLMARK_MYOGENESIS",
        n_members: 2,
        mean_nes: -0.5,
        n_pos: 1,
        n_neg: 1,
        n_sig_fdr: 0,
        consistency: 0.5,
        nes: { "GSE1:a": 0.8, "GSE2:b": -1.7 },
        fdr: { "GSE1:a": 0.6, "GSE2:b": 0.4 },
      },
    ],
  };

  it("draws one bubble per tested dataset and a cross where a set was not tested", () => {
    const { getAllByRole, getAllByText, getByText } = render(<PathwayMatrix pathways={pathways} />);
    expect(getAllByRole("graphics-symbol")).toHaveLength(5);
    expect(getAllByText("×")).toHaveLength(1);
    expect(getByText("INTERFERON GAMMA RESPONSE")).toBeInTheDocument();
    expect(getByText("3/3")).toBeInTheDocument();
  });

  it("grows past a narrow container so every dataset stays reachable by scrolling", () => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get: () => 390,
    });
    const many = Array.from({ length: 17 }, (_, i) => `GSE${i}:x`);
    const wide: PathwaySynthesis = {
      ...pathways,
      members: many,
      terms: [
        {
          ...pathways.terms[0],
          n_members: 17,
          nes: Object.fromEntries(many.map((m) => [m, 2])),
          fdr: Object.fromEntries(many.map((m) => [m, 0.01])),
        },
      ],
    };
    const { container } = render(<PathwayMatrix pathways={wide} />);
    const svg = container.querySelector("svg");
    // 22px minimum per dataset plus the label and count columns
    expect(Number(svg?.getAttribute("width"))).toBeGreaterThan(22 * 17 + 120);
    expect(svg?.parentElement?.className).toContain("overflow-x-auto");
  });
});

describe("ReplicationStrip", () => {
  const gene = (symbol: string, lfc: number): GeneMeta => ({
    gene_id: symbol,
    symbol,
    n_tested: 3,
    n_with_padj: 3,
    n_sig: 2,
    n_up_sig: 2,
    n_down_sig: 0,
    n_pos: 3,
    n_neg: 0,
    n_agree_pooled: 3,
    replication: 0.67,
    sign_consistency: 1,
    pooled_log2fc: lfc,
    padj: 1e-6,
    robust: true,
    effects: {
      "GSE1:a": { log2fc: lfc, se: 0.2, padj: 1e-4, n_samples: 20 },
      "GSE2:b": { log2fc: lfc * 0.5, se: 0.3, padj: 0.3, n_samples: 8 },
      "GSE3:c": { log2fc: null, se: null, padj: null, n_samples: null },
    },
  });

  it("shows every dataset plus the pooled column for each gene", () => {
    const { getAllByRole, getAllByText } = render(
      <ReplicationStrip
        rows={[gene("IL17A", 3), gene("S100A7", 5)]}
        members={members}
        alpha={0.05}
      />,
    );
    expect(getAllByRole("graphics-symbol")).toHaveLength(2 * (members.length + 1));
    expect(getAllByText("×")).toHaveLength(2);
    expect(getAllByText("pooled")).toHaveLength(1);
  });

  it("draws nothing for a report written without per-dataset estimates", () => {
    // Reports from before the field existed carry no effects at all: that is "unavailable",
    // not "not tested", so no cross may be drawn.
    const legacy = { ...gene("IL17A", 3), effects: {} };
    expect(hasPerMemberEffects([legacy])).toBe(false);
    const { container } = render(
      <ReplicationStrip rows={[legacy]} members={members} alpha={0.05} />,
    );
    expect(container.querySelector("svg")).toBeNull();
  });

  it("grows past a narrow container so the pooled column stays reachable by scrolling", () => {
    Object.defineProperty(HTMLElement.prototype, "clientWidth", {
      configurable: true,
      get: () => 390,
    });
    const many = Array.from({ length: 17 }, (_, i) => `GSE${i}:x`);
    const row = {
      ...gene("IL17A", 3),
      effects: Object.fromEntries(many.map((m) => [m, { log2fc: 1, se: 0.1, padj: 0.01 }])),
    };
    const { container } = render(<ReplicationStrip rows={[row]} members={many} alpha={0.05} />);
    const svg = container.querySelector("svg");
    expect(svg).not.toBeNull();
    // 18px minimum per column, 17 datasets + pooled, plus the label and header overhang
    expect(Number(svg?.getAttribute("width"))).toBeGreaterThan(18 * 18 + 72);
    expect(svg?.parentElement?.className).toContain("overflow-x-auto");
  });
});

describe("PathwayNetwork", () => {
  const term = (name: string, nes: number, genes: string[]): EnrichmentTerm => ({
    term: name,
    nes,
    pvalue: 0,
    fdr: 0.001,
    size: 200,
    lead_genes: genes,
  });
  const terms = [
    term("HALLMARK_A", 2, ["STAT1", "IRF1", "GBP1"]),
    term("HALLMARK_B", 1.5, ["STAT1", "OAS1"]),
    term("HALLMARK_C", -2, ["MYH7"]),
  ];

  it("links pathways to their leading genes, shares genes between sets, and selects a set on click", () => {
    const onSelectTerm = vi.fn();
    const onSelectGene = vi.fn();
    const { getAllByRole, getByLabelText } = render(
      <PathwayNetwork
        terms={terms}
        selected={null}
        onSelectTerm={onSelectTerm}
        onSelectGene={onSelectGene}
      />,
    );
    // 3 pathways + 5 distinct genes
    expect(getAllByRole("graphics-symbol")).toHaveLength(8);
    expect(getByLabelText("STAT1, in 2 of these sets")).toBeInTheDocument();
    fireEvent.click(getByLabelText(/^A: NES/));
    expect(onSelectTerm).toHaveBeenCalledWith(terms[0]);
    fireEvent.click(getByLabelText("STAT1, in 2 of these sets"));
    expect(onSelectGene).toHaveBeenCalledWith("STAT1");
  });
});

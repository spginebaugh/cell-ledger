import { fireEvent, render } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { countPooled, fromRawPooled, memberAgreement, wallOrder } from "@/lib/pooled";
import { AgreementWall } from "../agreement-wall";
import { PooledVolcano } from "../pooled-volcano";
import { colorCap } from "../replication-strip";

const W = 700;
const H = 480;

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
  HTMLElement.prototype.getBoundingClientRect = () =>
    ({ left: 0, top: 0, width: W, height: H, right: W, bottom: H, x: 0, y: 0 }) as DOMRect;
  HTMLCanvasElement.prototype.getContext = (() => null) as never;
});
afterEach(() => vi.unstubAllGlobals());

// Three pooled datasets and one set aside with its labels reversed. Four genes: two robust
// (one each way), one called by the pool but seen in one study, one not called.
const table = fromRawPooled({
  n: 4,
  alpha: 0.05,
  lfc_threshold: 1,
  min_studies: 3,
  lfc_scale: 100,
  nlp_scale: 10,
  members: [
    { label: "GSE1:a_vs_b", gse: "GSE1", pooled: true, flags: [], n_samples: 40 },
    { label: "GSE2:a_vs_b", gse: "GSE2", pooled: true, flags: [], n_samples: 20 },
    { label: "GSE3:a_vs_b", gse: "GSE3", pooled: true, flags: [], n_samples: 6 },
    {
      label: "GSE4:a_vs_b",
      gse: "GSE4",
      pooled: false,
      flags: ["labels_reversed"],
      n_samples: 8,
    },
  ],
  gene_id: ["10", "20", "30", "40"],
  symbol: ["UP1", "DOWN1", "WEAK", null],
  log2fc: [312, -250, 150, 10],
  nlp: [120, 80, 25, 2],
  n_tested: [3, 3, 3, 3],
  n_agree: [3, 3, 2, 1],
  n_sig: [3, 3, 1, 0],
  robust: [1, 1, 0, 0],
  member_lfc: [
    [300, -240, 140, 5],
    [330, -260, 160, 20],
    [310, null, -20, 10],
    [-290, 250, -100, 0],
  ],
  member_se: [
    [20, 20, 40, 30],
    [30, 30, 50, 30],
    [60, null, 80, 30],
    [50, 50, 50, 30],
  ],
  member_sig: [
    [1, 1, 1, 0],
    [1, 1, 0, 0],
    [1, 0, 0, 0],
    [1, 1, 0, 0],
  ],
});

describe("pooled table decoding", () => {
  it("rescales the quantised columns and keeps untested cells as NaN", () => {
    expect(table.log2fc[0]).toBeCloseTo(3.12);
    expect(table.negLog[1]).toBeCloseTo(8);
    expect(table.memberLfc[2][1]).toBeNaN();
    expect(table.memberSe[1][0]).toBeCloseTo(0.3);
    expect(table.members[3].pooled).toBe(false);
  });
  it("orders the wall as two blocks and scores each dataset's agreement over robust genes", () => {
    expect(wallOrder(table)).toEqual([0, 1]);
    // GSE3 tested one robust gene and agreed; GSE4 tested both and opposed both
    expect(memberAgreement(table)).toEqual([1, 1, 1, 0]);
    expect(countPooled(table, 0.05, 1)).toEqual({ up: 2, down: 1, pooled: 4 });
  });
});

describe("AgreementWall", () => {
  it("names the blocks, every dataset and its agreement share", () => {
    const { getByRole, getByText } = render(<AgreementWall table={table} />);
    expect(getByRole("img").getAttribute("aria-label")).toContain(
      "2 robust genes across 4 datasets: 1 higher in case, 1 higher in control",
    );
    expect(getByText("GSE4")).toBeTruthy();
    expect(getByText("set aside")).toBeTruthy();
    expect(getByText("0%")).toBeTruthy();
  });
  it("opens a gene when a single-gene row is clicked", () => {
    const onSelect = vi.fn();
    const { getByRole } = render(<AgreementWall table={table} onSelect={onSelect} />);
    const canvas = getByRole("img");
    // two rows fill the plot: the top half is UP1 in every column
    fireEvent.click(canvas, { clientX: 130, clientY: 120 });
    expect(onSelect).toHaveBeenCalledWith("UP1", "10");
    fireEvent.click(canvas, { clientX: 130, clientY: 400 });
    expect(onSelect).toHaveBeenLastCalledWith("DOWN1", "20");
  });
});

describe("PooledVolcano", () => {
  it("counts the called genes and reports the symbol and GeneID under a click", () => {
    const onSelect = vi.fn();
    const { getByRole } = render(
      <PooledVolcano
        table={table}
        alpha={0.05}
        lfc={1}
        highlight={new Set()}
        onSelect={onSelect}
      />,
    );
    const canvas = getByRole("img");
    expect(canvas.getAttribute("aria-label")).toContain(
      "2 genes higher in case, 1 higher in control",
    );
    for (let x = 0; x <= W; x += 6)
      for (let y = 0; y <= 440; y += 6) fireEvent.click(canvas, { clientX: x, clientY: y });
    const picked = new Map(onSelect.mock.calls.map(([s, id]) => [s, id]));
    expect(picked).toEqual(
      new Map([
        ["UP1", "10"],
        ["DOWN1", "20"],
        ["WEAK", "30"],
      ]),
    );
  });
});

describe("colorCap", () => {
  const gene = (pooled: number, effects: Record<string, number>) =>
    ({
      gene_id: String(pooled),
      pooled_log2fc: pooled,
      effects: Object.fromEntries(Object.entries(effects).map(([k, v]) => [k, { log2fc: v }])),
    }) as never;
  it("saturates near the top of the fold changes on show, never below 1", () => {
    expect(colorCap([gene(0.3, { a: 0.2, b: -0.4 })], ["a", "b"])).toBe(1);
    // 90th percentile of |2, 6, 7, 8, 5, 6.5| is 8 -> rounded up to the half
    expect(colorCap([gene(2, { a: 6, b: 7 }), gene(8, { a: 5, b: 6.5 })], ["a", "b"])).toBe(8);
    expect(colorCap([], ["a"])).toBe(1);
  });
});

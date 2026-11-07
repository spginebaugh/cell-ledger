import { describe, expect, it } from "vitest";
import { countSignificant, decodeVolcano, fromRaw, isGzip } from "../volcano";

const raw = {
  n: 4,
  alpha: 0.05,
  lfc_threshold: 1,
  columns: ["gene_id", "symbol", "base_mean", "log2fc", "padj"],
  gene_id: ["1", "2", "3", "4"],
  symbol: ["A", "B", null, "D"],
  base_mean: [10, 20, 30, 40],
  log2fc: [2.5, -1.5, 0.2, 3],
  padj: [1e-10, 0.01, null, 0.2],
};

describe("volcano table", () => {
  it("keeps nulls as NaN and derives -log10", () => {
    const t = fromRaw(raw);
    expect(t.n).toBe(4);
    expect(Number.isNaN(t.padj[2])).toBe(true);
    expect(t.negLog[0]).toBeCloseTo(10);
    expect(t.symbol[2]).toBeNull();
  });
  it("counts significant genes by both thresholds", () => {
    const t = fromRaw(raw);
    expect(countSignificant(t, 0.05, 1)).toEqual({ up: 1, down: 1, tested: 3 });
    expect(countSignificant(t, 0.5, 0)).toEqual({ up: 2, down: 1, tested: 3 });
  });
  it("decodes plain JSON bytes and detects gzip magic", async () => {
    const bytes = new TextEncoder().encode(JSON.stringify(raw));
    const t = await decodeVolcano(bytes.buffer as ArrayBuffer);
    expect(t.geneId).toEqual(["1", "2", "3", "4"]);
    expect(isGzip(new Uint8Array([0x1f, 0x8b, 0x08]))).toBe(true);
    expect(isGzip(bytes)).toBe(false);
  });
});

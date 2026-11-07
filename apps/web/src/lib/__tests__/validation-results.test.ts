import { describe, expect, it } from "vitest";
import { decodeLfc, decodePoints } from "@/lib/validation";
import { VALIDATION_RESULTS } from "@/lib/validation-results";

describe("hard-coded pipeline validation results", () => {
  const { datasets, comparisons, maxPoints } = VALIDATION_RESULTS;

  it("covers every dataset with at least one comparison, and nothing else", () => {
    const gses = new Set(datasets.map((d) => d.gse));
    expect(gses.size).toBe(datasets.length);
    for (const c of comparisons) expect(gses.has(c.gse)).toBe(true);
    for (const d of datasets) expect(comparisons.some((c) => c.gse === d.gse)).toBe(true);
    expect(new Set(comparisons.map((c) => `${c.gse}/${c.contrast}`)).size).toBe(comparisons.length);
  });

  it("has agreement statistics in range", () => {
    for (const c of comparisons) {
      expect(c.shared).toBeGreaterThan(1000);
      expect(c.r2).toBeGreaterThan(0.5);
      expect(c.r2).toBeLessThanOrEqual(1);
      expect(c.spearman).toBeGreaterThan(0.8);
      expect(c.spearman).toBeLessThanOrEqual(1);
      expect(c.lim).toBeGreaterThan(0);
    }
  });

  it("decodes every point sample consistently", () => {
    for (const c of comparisons) {
      const pts = decodePoints(c);
      expect(pts.n).toBe(c.shown);
      expect(pts.n).toBeLessThanOrEqual(Math.min(maxPoints, c.shared));
      expect(pts.published.length).toBe(c.shown);
      expect(pts.ours.length).toBe(c.shown);
      expect(pts.symbols.length).toBe(c.shown);
      // the sample's own fold changes correlate at least roughly like the full table
      let sx = 0;
      let sy = 0;
      let sxx = 0;
      let syy = 0;
      let sxy = 0;
      for (let i = 0; i < pts.n; i++) {
        const a = pts.published[i];
        const b = pts.ours[i];
        sx += a;
        sy += b;
        sxx += a * a;
        syy += b * b;
        sxy += a * b;
      }
      const n = pts.n;
      const r = (n * sxy - sx * sy) / Math.sqrt((n * sxx - sx * sx) * (n * syy - sy * sy));
      expect(r * r).toBeGreaterThan(0.5);
    }
  });

  it("round-trips the Int16 packing", () => {
    // 1.23, -4.56, 0 as little-endian Int16 hundredths
    const bytes = new Uint8Array(new Int16Array([123, -456, 0]).buffer);
    const b64 = btoa(String.fromCharCode(...bytes));
    expect(Array.from(decodeLfc(b64))).toEqual([1.23, -4.56, 0]);
  });
});

import { describe, expect, it } from "vitest";
import { fromRawGsea, runningScore } from "../gsea";

describe("runningScore", () => {
  // Six genes ranked 3, 2, 1, -1, -2, -3; the set is the top two. With p = 1 the score climbs
  // 3/5 then 2/5 to exactly 1 at rank 2, then falls by 1/4 per miss back to zero.
  const table = fromRawGsea({
    n: 6,
    ranked: ["A", "B", "C", "D", "E", "F"],
    metric: [3, 2, 1, -1, -2, -3],
    terms: { UP: { hits: [0, 1], es: 1, peak: 1 } },
  });

  it("reproduces the GSEA running score and its peak", () => {
    const r = runningScore(table, [0, 1]);
    expect(Array.from(r.res).map((v) => Number(v.toFixed(6)))).toEqual([
      0.6, 1, 0.75, 0.5, 0.25, 0,
    ]);
    expect(r.peak).toBe(1);
    expect(r.es).toBeCloseTo(1, 9);
    expect(r.leading).toEqual([0, 1]);
  });

  it("gives a negative score with a trailing leading edge for a set at the bottom", () => {
    const r = runningScore(table, [4, 5]);
    expect(r.es).toBeCloseTo(-1, 9);
    expect(r.peak).toBe(3);
    expect(r.leading).toEqual([4, 5]);
  });

  it("finds where the metric crosses zero", () => {
    expect(table.zeroCross).toBe(3);
  });
});

import { describe, expect, it } from "vitest";
import { EVAL_RESULTS } from "@/lib/eval-results";

describe("hard-coded eval results", () => {
  const { meta, summary, cases } = EVAL_RESULTS;

  it("has every case once, with a run for each system", () => {
    expect(cases).toHaveLength(meta.cases);
    expect(new Set(cases.map((c) => c.id)).size).toBe(cases.length);
  });

  it("adds up: per-case passes and first moves match the headline totals", () => {
    for (const s of ["baseline", "specialist"] as const) {
      expect(cases.filter((c) => c[s].passed).length).toBe(summary[s].passed.n);
      expect(cases.filter((c) => c[s].actionCorrect).length).toBe(summary[s].actionAccuracy.n);
      expect(summary[s].passed.d).toBe(meta.cases);
      const found = cases.reduce((n, c) => n + c[s].recall.n, 0);
      expect(found).toBe(summary[s].recall.n);
    }
  });
});

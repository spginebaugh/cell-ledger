import { describe, expect, it } from "vitest";
import { fmtLfc, fmtP, fmtSeconds, verdictGlyph, verdictLabel, verdictTone } from "../format";
import { guessGenes, slugify } from "../ui-state";

describe("formatting", () => {
  it("formats p-values in scientific notation when small", () => {
    expect(fmtP(3.4e-12)).toBe("3.4e-12");
    expect(fmtP(0.0421)).toBe("0.04");
    expect(fmtP(null)).toBe("n/a");
    expect(fmtP(0)).toBe("<1e-300");
  });
  it("signs log fold changes", () => {
    expect(fmtLfc(1.234)).toBe("+1.23");
    expect(fmtLfc(-0.5)).toBe("−0.50"); // d3-format uses a true minus sign
  });
  it("formats durations", () => {
    expect(fmtSeconds(0.4)).toBe("400 ms");
    expect(fmtSeconds(12.78)).toBe("12.8 s");
    expect(fmtSeconds(130)).toBe("2 min 10 s");
  });
  it("maps verdicts to labels, tones and glyphs", () => {
    expect(verdictLabel("up")).toBe("Higher in case");
    expect(verdictTone("replicated_down")).toBe("control");
    expect(verdictGlyph("no_evidence")).toBe("–");
    expect(verdictTone("inconsistent")).toBe("amber");
  });
  it("guesses gene symbols from a question and slugifies names", () => {
    expect(guessGenes("Is IL17A higher in psoriasis lesional skin than CXCL9 in RNA-seq?")).toEqual(
      ["IL17A", "CXCL9"],
    );
    expect(slugify("Is IL17A higher?")).toBe("is_il17a_higher");
  });
});

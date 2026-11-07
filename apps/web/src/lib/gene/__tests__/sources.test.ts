import { describe, expect, it } from "vitest";
import {
  gtexTissueLabel,
  normalizeHpa,
  normalizeMyGene,
  normalizeUniProt,
  plddtColor,
  stringNetworkImageUrl,
} from "../sources";

describe("mygene normalisation", () => {
  it("flattens arrays and fills gaps", () => {
    const g = normalizeMyGene(
      {
        _id: "5156",
        symbol: "PDGFRA",
        name: "platelet derived growth factor receptor alpha",
        summary: "  This gene encodes...  ",
        alias: "CD140A",
        type_of_gene: "protein-coding",
        map_location: "4q12",
        ensembl: [{ gene: "ENSG00000134853" }, { gene: "ENSG00000999999" }],
        uniprot: { "Swiss-Prot": ["P16234", "Q00000"] },
      },
      "X",
    );
    expect(g.aliases).toEqual(["CD140A"]);
    expect(g.ensembl).toBe("ENSG00000134853");
    expect(g.uniprot).toBe("P16234");
    expect(g.summary).toBe("This gene encodes...");
  });
  it("handles a non-coding gene with nothing but a name", () => {
    const g = normalizeMyGene(
      { _id: "100506229", name: "lnc 1093", type_of_gene: "ncRNA" },
      "LINC01093",
    );
    expect(g.symbol).toBe("LINC01093");
    expect(g.summary).toBeNull();
    expect(g.uniprot).toBeNull();
    expect(g.aliases).toEqual([]);
  });
});

describe("hpa normalisation", () => {
  it("reads locations and sorts enriched cell types", () => {
    const h = normalizeHpa({
      "Subcellular main location": ["Nucleoplasm", "Plasma membrane"],
      "Subcellular additional location": null,
      "Protein class": ["Enzymes"],
      Evidence: "Evidence at protein level",
      "RNA tissue specificity": "Tissue enhanced",
      "RNA single cell type specific nCPM": { Fibroblasts: "245.6", "Leydig cells": "301.5" },
    });
    expect(h.mainLocations).toEqual(["Nucleoplasm", "Plasma membrane"]);
    expect(h.additionalLocations).toEqual([]);
    expect(h.cellTypeEnriched.map((c) => c.cellType)).toEqual(["Leydig cells", "Fibroblasts"]);
    expect(h.tissueDistribution).toBeNull();
  });
});

describe("uniprot normalisation", () => {
  it("collects function text and distinct locations", () => {
    const u = normalizeUniProt({
      primaryAccession: "P16234",
      proteinDescription: { recommendedName: { fullName: { value: "PDGFR alpha" } } },
      comments: [
        { commentType: "FUNCTION", texts: [{ value: "Tyrosine-protein kinase." }] },
        {
          commentType: "SUBCELLULAR LOCATION",
          subcellularLocations: [
            { location: { value: "Cell membrane", id: "SL-0039" } },
            { location: { value: "Cell membrane", id: "SL-0039" } },
            { location: { value: "Golgi apparatus" } },
          ],
        },
      ],
      sequence: { length: 1089 },
    });
    expect(u.functionText).toBe("Tyrosine-protein kinase.");
    expect(u.locations).toEqual(["Cell membrane", "Golgi apparatus"]);
    expect(u.length).toBe(1089);
  });
});

describe("labels and urls", () => {
  it("turns GTEx ids into readable names", () => {
    expect(gtexTissueLabel("Liver")).toBe("Liver");
    expect(gtexTissueLabel("Brain_Putamen_basal_ganglia")).toBe("Brain, putamen");
    expect(gtexTissueLabel("Brain_Frontal_Cortex_BA9")).toBe("Brain, frontal cortex");
    expect(gtexTissueLabel("Cells_EBV-transformed_lymphocytes")).toBe(
      "EBV-transformed lymphocytes",
    );
    expect(gtexTissueLabel("Colon_Transverse")).toBe("Colon, transverse");
  });
  it("builds a pinned STRING image url for human", () => {
    const u = new URL(stringNetworkImageUrl("PDGFRA"));
    expect(u.hostname).toBe("version-12-0.string-db.org");
    expect(u.searchParams.get("species")).toBe("9606");
    expect(u.searchParams.get("identifiers")).toBe("PDGFRA");
  });
  it("uses the AlphaFold confidence bands", () => {
    expect(plddtColor(95)).toBe("#0053d6");
    expect(plddtColor(70)).toBe("#65cbf3");
    expect(plddtColor(69.9)).toBe("#ffdb13");
    expect(plddtColor(10)).toBe("#ff7d45");
  });
});

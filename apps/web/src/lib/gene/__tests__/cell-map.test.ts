import { describe, expect, it } from "vitest";
import svg from "../../../../public/gene/cell.svg?raw";
import {
  CELL_COMPARTMENTS,
  cellHighlightsFromHpa,
  cellHighlightsFromUniProt,
  hpaLocationToCompartment,
  snake,
  uniprotLocationToCompartment,
} from "../cell-map";

describe("cell compartments", () => {
  it("every compartment id and alias is drawn in cell.svg", () => {
    for (const c of CELL_COMPARTMENTS) {
      expect(svg, c.id).toContain(`id="${c.id}"`);
      for (const a of c.aliases) expect(svg, a).toMatch(new RegExp(`class="[^"]*\\b${a}\\b`));
    }
  });
  it("maps HPA names by a string transform, including aliases", () => {
    expect(snake("Rods & Rings")).toBe("rods_and_rings");
    expect(hpaLocationToCompartment("Plasma membrane")).toBe("plasma_membrane");
    expect(hpaLocationToCompartment("Cell Junctions")).toBe("plasma_membrane");
    expect(hpaLocationToCompartment("Nucleoli fibrillar center")).toBe("nucleoli_fibrillar_center");
    expect(hpaLocationToCompartment("Mitotic spindle")).toBe("microtubules");
    expect(hpaLocationToCompartment("Vesicles")).toBe("endosomes");
    expect(hpaLocationToCompartment("Primary cilium")).toBeNull();
  });
  it("maps the UniProt vocabulary by prefix, most specific first", () => {
    expect(uniprotLocationToCompartment("Cell membrane")).toBe("plasma_membrane");
    expect(uniprotLocationToCompartment("Cell projection, cilium")).toBe("plasma_membrane");
    expect(uniprotLocationToCompartment("Nucleus speckle")).toBe("nuclear_speckles");
    expect(uniprotLocationToCompartment("Nucleus")).toBe("nucleoplasm");
    expect(
      uniprotLocationToCompartment(
        "Cytoplasm, cytoskeleton, microtubule organizing center, centrosome",
      ),
    ).toBe("centrosome");
    expect(uniprotLocationToCompartment("Mitochondrion inner membrane")).toBe("mitochondria");
    expect(uniprotLocationToCompartment("Secreted, extracellular space")).toBe("secreted_proteins");
    expect(uniprotLocationToCompartment("Virion")).toBeNull();
  });
  it("keeps main over additional when both name the same drawing, and lists the undrawn", () => {
    const h = cellHighlightsFromHpa(
      ["Plasma membrane", "Primary cilium"],
      ["Cell Junctions", "Cytosol"],
    );
    expect(h.byCompartment.get("plasma_membrane")).toBe("main");
    expect(h.byCompartment.get("cytosol")).toBe("additional");
    expect(h.undrawn).toEqual(["Primary cilium"]);
    expect(h.source).toBe("hpa");
    const u = cellHighlightsFromUniProt(["Golgi apparatus", "Virion"]);
    expect([...u.byCompartment.keys()]).toEqual(["golgi_apparatus"]);
    expect(u.undrawn).toEqual(["Virion"]);
  });
});

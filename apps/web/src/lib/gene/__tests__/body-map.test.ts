import { describe, expect, it } from "vitest";
import female from "../../../../public/gene/body-female.svg?raw";
import male from "../../../../public/gene/body-male.svg?raw";
import {
  BODY_ORGANS,
  expressionRamp,
  GTEX_CELL_LINES,
  organForElementId,
  preferredSex,
  summariseByOrgan,
  unplacedTissues,
} from "../body-map";
import type { GtexTissue } from "../sources";

/** The 54 tissues GTEx v10 reports, as returned by medianGeneExpression. */
const GTEX_TISSUES = [
  "Adipose_Subcutaneous",
  "Adipose_Visceral_Omentum",
  "Adrenal_Gland",
  "Artery_Aorta",
  "Artery_Coronary",
  "Artery_Tibial",
  "Bladder",
  "Brain_Amygdala",
  "Brain_Anterior_cingulate_cortex_BA24",
  "Brain_Caudate_basal_ganglia",
  "Brain_Cerebellar_Hemisphere",
  "Brain_Cerebellum",
  "Brain_Cortex",
  "Brain_Frontal_Cortex_BA9",
  "Brain_Hippocampus",
  "Brain_Hypothalamus",
  "Brain_Nucleus_accumbens_basal_ganglia",
  "Brain_Putamen_basal_ganglia",
  "Brain_Spinal_cord_cervical_c-1",
  "Brain_Substantia_nigra",
  "Breast_Mammary_Tissue",
  "Cells_Cultured_fibroblasts",
  "Cells_EBV-transformed_lymphocytes",
  "Cervix_Ectocervix",
  "Cervix_Endocervix",
  "Colon_Sigmoid",
  "Colon_Transverse",
  "Esophagus_Gastroesophageal_Junction",
  "Esophagus_Mucosa",
  "Esophagus_Muscularis",
  "Fallopian_Tube",
  "Heart_Atrial_Appendage",
  "Heart_Left_Ventricle",
  "Kidney_Cortex",
  "Kidney_Medulla",
  "Liver",
  "Lung",
  "Minor_Salivary_Gland",
  "Muscle_Skeletal",
  "Nerve_Tibial",
  "Ovary",
  "Pancreas",
  "Pituitary",
  "Prostate",
  "Skin_Not_Sun_Exposed_Suprapubic",
  "Skin_Sun_Exposed_Lower_leg",
  "Small_Intestine_Terminal_Ileum",
  "Spleen",
  "Stomach",
  "Testis",
  "Thyroid",
  "Uterus",
  "Vagina",
  "Whole_Blood",
];

const tissues: GtexTissue[] = GTEX_TISSUES.map((id, i) => ({
  id,
  median: id === "Liver" ? 500 : id === "Testis" ? 50 : (i % 7) + 1,
  ontologyId: "UBERON:0",
}));

describe("body organs", () => {
  it("every drawing id exists in the drawing for its sex", () => {
    for (const o of BODY_ORGANS) {
      const drawings = o.sex === "male" ? [male] : o.sex === "female" ? [female] : [male, female];
      for (const id of o.ids)
        for (const d of drawings) expect(d, `${o.key}:${id}`).toContain(`id="${id}"`);
    }
  });
  it("places every GTEx tissue except the cultured cell lines", () => {
    const left = unplacedTissues(tissues).map((t) => t.id);
    expect(new Set(left)).toEqual(GTEX_CELL_LINES);
  });
  it("lists each tissue under exactly one organ", () => {
    const seen = new Map<string, number>();
    for (const o of BODY_ORGANS) for (const t of o.tissues) seen.set(t, (seen.get(t) ?? 0) + 1);
    for (const [t, n] of seen) expect(n, t).toBe(1);
  });
  it("summarises by the highest tissue and ranks organs", () => {
    const v = summariseByOrgan(tissues);
    expect(v[0].organ.key).toBe("liver");
    expect(v[0].max).toBe(500);
    const brain = v.find((x) => x.organ.key === "brain");
    expect(brain?.tissues).toHaveLength(13);
    expect(brain?.tissues[0].median).toBeGreaterThanOrEqual(brain?.tissues[12].median ?? 0);
    expect(organForElementId("UBERON_0002107")?.key).toBe("liver");
    expect(organForElementId("UBERON_0000000")).toBeNull();
  });
  it("picks the drawing that shows the most expressed sex-specific organ", () => {
    expect(preferredSex(summariseByOrgan(tissues))).toBe("male");
    expect(preferredSex([])).toBe("female");
  });
  it("ramps on a log scale and clamps", () => {
    expect(expressionRamp(0, 100)).toBe(0);
    expect(expressionRamp(100, 100)).toBe(1);
    expect(expressionRamp(9, 99)).toBeCloseTo(0.5, 5);
    expect(expressionRamp(5, 0)).toBe(0);
  });
});

/** Place GTEx tissues onto the Expression Atlas human anatomograms in public/gene/body-*.svg.
 *
 * The drawings (EMBL-EBI Expression Atlas, CC BY 4.0) give every organ an element whose id
 * is an ontology term (UBERON_..., CL_...). GTEx samples are finer than the drawing in some
 * places (13 brain regions, 3 esophagus layers) and coarser in others, so each organ below
 * lists the drawing ids it paints and the GTEx tissues it summarises. An organ's colour is
 * the highest median TPM among its tissues; the hover readout lists them all.
 */

import type { GtexTissue } from "./sources";

export type BodyOrgan = {
  key: string;
  label: string;
  /** element ids in the drawing; empty for tissues that span the whole figure */
  ids: string[];
  /** GTEx tissueSiteDetailId values */
  tissues: string[];
  /** which drawing(s) have this organ */
  sex?: "male" | "female";
};

const BRAIN_TISSUES = [
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
];

export const BODY_ORGANS: BodyOrgan[] = [
  {
    key: "brain",
    label: "Brain",
    ids: [
      "UBERON_0000955",
      "UBERON_0000956",
      "UBERON_0000451",
      "UBERON_0001870",
      "UBERON_0001871",
      "UBERON_0001876",
      "UBERON_0001954",
      "UBERON_0002037",
      "UBERON_0002245",
      "UBERON_0002421",
    ],
    tissues: BRAIN_TISSUES,
  },
  { key: "pituitary", label: "Pituitary", ids: ["UBERON_0000007"], tissues: ["Pituitary"] },
  { key: "thyroid", label: "Thyroid", ids: ["UBERON_0002046"], tissues: ["Thyroid"] },
  {
    key: "salivary",
    label: "Salivary gland",
    ids: ["UBERON_0001044", "UBERON_0001736", "UBERON_0001831"],
    tissues: ["Minor_Salivary_Gland"],
  },
  {
    key: "esophagus",
    label: "Esophagus",
    ids: ["UBERON_0001043", "UBERON_0007650"],
    tissues: ["Esophagus_Mucosa", "Esophagus_Muscularis", "Esophagus_Gastroesophageal_Junction"],
  },
  { key: "lung", label: "Lung", ids: ["UBERON_0002048"], tissues: ["Lung"] },
  {
    key: "heart",
    label: "Heart",
    ids: ["UBERON_0000948", "UBERON_0002084", "UBERON_0006618", "UBERON_0002079"],
    tissues: ["Heart_Left_Ventricle", "Heart_Atrial_Appendage"],
  },
  {
    key: "artery",
    label: "Arteries",
    ids: ["UBERON_0000947", "UBERON_0001621"],
    tissues: ["Artery_Aorta", "Artery_Coronary", "Artery_Tibial"],
  },
  { key: "breast", label: "Breast", ids: ["UBERON_0000310"], tissues: ["Breast_Mammary_Tissue"] },
  { key: "liver", label: "Liver", ids: ["UBERON_0002107"], tissues: ["Liver"] },
  { key: "stomach", label: "Stomach", ids: ["UBERON_0000945"], tissues: ["Stomach"] },
  { key: "pancreas", label: "Pancreas", ids: ["UBERON_0001264"], tissues: ["Pancreas"] },
  { key: "spleen", label: "Spleen", ids: ["UBERON_0002106"], tissues: ["Spleen"] },
  { key: "adrenal", label: "Adrenal gland", ids: ["UBERON_0002369"], tissues: ["Adrenal_Gland"] },
  {
    key: "kidney",
    label: "Kidney",
    ids: ["UBERON_0002113", "UBERON_0001225"],
    tissues: ["Kidney_Cortex", "Kidney_Medulla"],
  },
  {
    key: "small_intestine",
    label: "Small intestine",
    ids: ["UBERON_0002108", "UBERON_0002116", "UBERON_0002114"],
    tissues: ["Small_Intestine_Terminal_Ileum"],
  },
  {
    key: "colon",
    label: "Colon",
    ids: ["UBERON_0001155", "UBERON_0001052", "UBERON_0001153"],
    tissues: ["Colon_Transverse", "Colon_Sigmoid"],
  },
  { key: "bladder", label: "Bladder", ids: ["UBERON_0001255"], tissues: ["Bladder"] },
  {
    key: "adipose",
    label: "Adipose tissue",
    ids: ["UBERON_0001013"],
    tissues: ["Adipose_Subcutaneous", "Adipose_Visceral_Omentum"],
  },
  {
    key: "skin",
    label: "Skin",
    ids: [] /* skin is the whole silhouette */,
    tissues: ["Skin_Sun_Exposed_Lower_leg", "Skin_Not_Sun_Exposed_Suprapubic"],
  },
  {
    key: "muscle",
    label: "Skeletal muscle",
    ids: ["UBERON_0001134"],
    tissues: ["Muscle_Skeletal"],
  },
  {
    key: "nerve",
    label: "Peripheral nerve",
    ids: [] /* the nerve network spans the figure */,
    tissues: ["Nerve_Tibial"],
  },
  {
    key: "blood",
    label: "Whole blood",
    ids: [] /* the vessel network spans the figure */,
    tissues: ["Whole_Blood"],
  },
  { key: "testis", label: "Testis", ids: ["UBERON_0000473"], tissues: ["Testis"], sex: "male" },
  {
    key: "prostate",
    label: "Prostate",
    ids: ["UBERON_0002367"],
    tissues: ["Prostate"],
    sex: "male",
  },
  { key: "ovary", label: "Ovary", ids: ["UBERON_0000992"], tissues: ["Ovary"], sex: "female" },
  {
    key: "fallopian",
    label: "Fallopian tube",
    ids: ["UBERON_0003889"],
    tissues: ["Fallopian_Tube"],
    sex: "female",
  },
  {
    key: "uterus",
    label: "Uterus",
    ids: ["UBERON_0000995", "UBERON_0001295"],
    tissues: ["Uterus"],
    sex: "female",
  },
  {
    key: "cervix",
    label: "Cervix",
    ids: ["UBERON_0012249"],
    tissues: ["Cervix_Ectocervix", "Cervix_Endocervix"],
    sex: "female",
  },
  { key: "vagina", label: "Vagina", ids: ["UBERON_0000996"], tissues: ["Vagina"], sex: "female" },
];

/** GTEx "tissues" that are cultured cells and have no place on a body. */
export const GTEX_CELL_LINES = new Set([
  "Cells_Cultured_fibroblasts",
  "Cells_EBV-transformed_lymphocytes",
]);

const ORGAN_BY_ID = new Map<string, BodyOrgan>();
for (const o of BODY_ORGANS) for (const id of o.ids) ORGAN_BY_ID.set(id, o);

export function organForElementId(id: string): BodyOrgan | null {
  return ORGAN_BY_ID.get(id) ?? null;
}

export type OrganValue = {
  organ: BodyOrgan;
  /** highest median TPM among the organ's measured tissues */
  max: number;
  tissues: GtexTissue[];
};

/** Summarise GTEx tissues per organ; organs with no measured tissue are left out. */
export function summariseByOrgan(tissues: GtexTissue[]): OrganValue[] {
  const byId = new Map(tissues.map((t) => [t.id, t]));
  const out: OrganValue[] = [];
  for (const organ of BODY_ORGANS) {
    const have = organ.tissues.map((id) => byId.get(id)).filter((t): t is GtexTissue => !!t);
    if (have.length === 0) continue;
    have.sort((a, b) => b.median - a.median);
    out.push({ organ, max: have[0].median, tissues: have });
  }
  return out.sort((a, b) => b.max - a.max);
}

/** GTEx tissues not summarised by any organ (should only be the cell lines). */
export function unplacedTissues(tissues: GtexTissue[]): GtexTissue[] {
  const placed = new Set(BODY_ORGANS.flatMap((o) => o.tissues));
  return tissues.filter((t) => !placed.has(t.id));
}

/** Which drawing shows the organ with the highest expression; ties go to female (more organs drawn). */
export function preferredSex(values: OrganValue[]): "male" | "female" {
  for (const v of values) if (v.organ.sex) return v.organ.sex;
  return "female";
}

/** Position on a 0..1 ramp, log-scaled so that a 10x difference reads as a clear step. */
export function expressionRamp(median: number, max: number): number {
  if (!(max > 0) || !(median > 0)) return 0;
  const top = Math.log10(1 + max);
  return top > 0 ? Math.min(1, Math.log10(1 + median) / top) : 0;
}

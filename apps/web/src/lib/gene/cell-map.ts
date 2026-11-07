/** Map subcellular location names onto the compartments drawn in public/gene/cell.svg.
 *
 * The drawing is the Human Protein Atlas cell (CC BY 4.0). Each organelle is a `<g>` whose
 * id is the HPA location name in snake case, and whose class lists the aliases HPA folds
 * into the same drawing (e.g. `plasma_membrane cell_junctions`). HPA location strings
 * therefore map by a string transform; UniProt's vocabulary needs a small table.
 */

/** Every compartment group in the drawing, in the order the legend should list them. */
export const CELL_COMPARTMENTS: { id: string; label: string; aliases: string[] }[] = [
  { id: "nucleoplasm", label: "Nucleoplasm", aliases: ["nucleus"] },
  { id: "nuclear_membrane", label: "Nuclear membrane", aliases: [] },
  { id: "nuclear_bodies", label: "Nuclear bodies", aliases: [] },
  { id: "nuclear_speckles", label: "Nuclear speckles", aliases: [] },
  { id: "nucleoli", label: "Nucleoli", aliases: [] },
  { id: "nucleoli_rim", label: "Nucleoli rim", aliases: [] },
  { id: "nucleoli_fibrillar_center", label: "Nucleoli fibrillar center", aliases: [] },
  { id: "cytosol", label: "Cytosol", aliases: ["cytoplasmic_bodies"] },
  { id: "plasma_membrane", label: "Plasma membrane", aliases: ["cell_junctions"] },
  { id: "endoplasmic_reticulum", label: "Endoplasmic reticulum", aliases: [] },
  { id: "golgi_apparatus", label: "Golgi apparatus", aliases: [] },
  { id: "mitochondria", label: "Mitochondria", aliases: [] },
  { id: "endosomes", label: "Endosomes", aliases: ["vesicles"] },
  { id: "lysosomes", label: "Lysosomes", aliases: [] },
  { id: "peroxisomes", label: "Peroxisomes", aliases: [] },
  { id: "lipid_droplets", label: "Lipid droplets", aliases: [] },
  { id: "secreted_proteins", label: "Secreted", aliases: [] },
  { id: "actin_filaments", label: "Actin filaments", aliases: [] },
  { id: "intermediate_filaments", label: "Intermediate filaments", aliases: [] },
  {
    id: "microtubules",
    label: "Microtubules",
    aliases: ["midbody", "midbody_ring", "mitotic_spindle", "cytokinetic_bridge"],
  },
  { id: "microtubule_ends", label: "Microtubule ends", aliases: [] },
  { id: "centrosome", label: "Centrosome", aliases: [] },
  { id: "centriolar_satellite", label: "Centriolar satellite", aliases: [] },
  { id: "focal_adhesion_sites", label: "Focal adhesion sites", aliases: [] },
  { id: "rods_and_rings", label: "Rods & rings", aliases: [] },
];

const BY_KEY = new Map<string, string>();
for (const c of CELL_COMPARTMENTS) {
  BY_KEY.set(c.id, c.id);
  for (const a of c.aliases) BY_KEY.set(a, c.id);
}

export function snake(name: string): string {
  return name
    .trim()
    .toLowerCase()
    .replace(/&/g, "and")
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_|_$/g, "");
}

/** HPA location name -> compartment id in the drawing, or null if it is not drawn. */
export function hpaLocationToCompartment(name: string): string | null {
  return BY_KEY.get(snake(name)) ?? null;
}

/** UniProt subcellular-location vocabulary -> compartment id (prefix match, most specific first). */
const UNIPROT_PREFIXES: [string, string][] = [
  ["nucleus speckle", "nuclear_speckles"],
  ["nucleus membrane", "nuclear_membrane"],
  ["nucleus envelope", "nuclear_membrane"],
  ["nucleus, nucleolus", "nucleoli"],
  ["nucleolus", "nucleoli"],
  ["nucleus", "nucleoplasm"],
  ["cell membrane", "plasma_membrane"],
  ["apical cell membrane", "plasma_membrane"],
  ["basolateral cell membrane", "plasma_membrane"],
  ["cell junction", "plasma_membrane"],
  ["cell projection", "plasma_membrane"],
  ["cell surface", "plasma_membrane"],
  ["membrane raft", "plasma_membrane"],
  ["synapse", "plasma_membrane"],
  ["endoplasmic reticulum", "endoplasmic_reticulum"],
  ["golgi apparatus", "golgi_apparatus"],
  ["mitochondrion", "mitochondria"],
  ["lysosome", "lysosomes"],
  ["late endosome", "endosomes"],
  ["early endosome", "endosomes"],
  ["recycling endosome", "endosomes"],
  ["endosome", "endosomes"],
  ["cytoplasmic vesicle", "endosomes"],
  ["peroxisome", "peroxisomes"],
  ["lipid droplet", "lipid_droplets"],
  ["secreted", "secreted_proteins"],
  ["extracellular", "secreted_proteins"],
  ["cytoplasm, cytoskeleton, microtubule organizing center, centrosome", "centrosome"],
  ["cytoplasm, cytoskeleton, cilium", "microtubules"],
  ["cytoplasm, cytoskeleton, spindle", "microtubules"],
  ["cytoplasm, cytoskeleton, stress fiber", "actin_filaments"],
  ["cytoplasm, cytoskeleton", "microtubules"],
  ["cytoplasm, cytosol", "cytosol"],
  ["cytoplasm, perinuclear region", "cytosol"],
  ["cytoplasm", "cytosol"],
  ["cytosol", "cytosol"],
  ["focal adhesion", "focal_adhesion_sites"],
  ["midbody", "microtubules"],
  ["centrosome", "centrosome"],
];

export function uniprotLocationToCompartment(name: string): string | null {
  const n = name.trim().toLowerCase();
  for (const [prefix, id] of UNIPROT_PREFIXES) if (n.startsWith(prefix)) return id;
  return null;
}

export type CellHighlights = {
  /** compartment id -> emphasis */
  byCompartment: Map<string, "main" | "additional">;
  /** location names we could not draw, kept for the text list */
  undrawn: string[];
  source: "hpa" | "uniprot";
};

export function cellHighlightsFromHpa(main: string[], additional: string[]): CellHighlights {
  const byCompartment = new Map<string, "main" | "additional">();
  const undrawn: string[] = [];
  for (const [names, level] of [
    [main, "main"],
    [additional, "additional"],
  ] as const) {
    for (const name of names) {
      const id = hpaLocationToCompartment(name);
      if (!id) undrawn.push(name);
      else if (!byCompartment.has(id)) byCompartment.set(id, level);
    }
  }
  return { byCompartment, undrawn, source: "hpa" };
}

export function cellHighlightsFromUniProt(locations: string[]): CellHighlights {
  const byCompartment = new Map<string, "main" | "additional">();
  const undrawn: string[] = [];
  for (const name of locations) {
    const id = uniprotLocationToCompartment(name);
    if (!id) undrawn.push(name);
    else byCompartment.set(id, "main");
  }
  return { byCompartment, undrawn, source: "uniprot" };
}

export function compartmentLabel(id: string): string {
  return CELL_COMPARTMENTS.find((c) => c.id === id)?.label ?? id.replaceAll("_", " ");
}

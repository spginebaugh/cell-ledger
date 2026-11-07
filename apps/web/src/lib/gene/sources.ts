/** Public gene annotation sources behind the gene panel.
 *
 * Every call here is keyed on the gene alone (an NCBI GeneID, a symbol, or an accession
 * derived from them) and is made straight from the browser: each service answers with
 * `Access-Control-Allow-Origin: *`, needs no key, and is human-only in how we use it.
 */

const HUMAN_TAXON = 9606;

async function getJson<T>(url: string, init?: RequestInit): Promise<T> {
  const res = await fetch(url, { ...init, headers: { accept: "application/json" } });
  if (!res.ok) throw new Error(`${new URL(url).hostname} answered ${res.status}`);
  return (await res.json()) as T;
}

function first<T>(v: T | T[] | undefined | null): T | null {
  if (v === undefined || v === null) return null;
  return Array.isArray(v) ? (v[0] ?? null) : v;
}

// ------------------------------------------------------------------ mygene.info

export type GeneCore = {
  entrez: string;
  symbol: string;
  name: string;
  /** NCBI RefSeq summary paragraph, when NCBI wrote one. */
  summary: string | null;
  aliases: string[];
  /** "protein-coding", "ncRNA", "pseudo", ... */
  type: string | null;
  mapLocation: string | null;
  ensembl: string | null;
  /** Swiss-Prot (reviewed) accession. */
  uniprot: string | null;
};

type MyGeneHit = {
  _id: string;
  symbol?: string;
  name?: string;
  summary?: string;
  alias?: string | string[];
  type_of_gene?: string;
  map_location?: string;
  ensembl?: { gene: string } | { gene: string }[];
  uniprot?: { "Swiss-Prot"?: string | string[] };
};

export function normalizeMyGene(hit: MyGeneHit, fallbackSymbol: string): GeneCore {
  const alias = hit.alias === undefined ? [] : Array.isArray(hit.alias) ? hit.alias : [hit.alias];
  const ens = first(hit.ensembl);
  return {
    entrez: hit._id,
    symbol: hit.symbol ?? fallbackSymbol,
    name: hit.name ?? "",
    summary: hit.summary?.trim() || null,
    aliases: alias,
    type: hit.type_of_gene ?? null,
    mapLocation: hit.map_location ?? null,
    ensembl: ens?.gene ?? null,
    uniprot: first(hit.uniprot?.["Swiss-Prot"]),
  };
}

const MYGENE_FIELDS =
  "symbol,name,summary,alias,type_of_gene,map_location,ensembl.gene,uniprot.Swiss-Prot";

/** By NCBI GeneID when the caller has one; otherwise by symbol, preferring an exact match. */
export async function fetchGeneCore(entrez: string | null, symbol: string): Promise<GeneCore> {
  if (entrez) {
    const hit = await getJson<MyGeneHit>(
      `https://mygene.info/v3/gene/${encodeURIComponent(entrez)}?fields=${MYGENE_FIELDS}&species=human`,
    );
    return normalizeMyGene(hit, symbol);
  }
  const q = await getJson<{ hits: MyGeneHit[] }>(
    `https://mygene.info/v3/query?q=symbol:${encodeURIComponent(symbol)}&species=human&fields=${MYGENE_FIELDS}&size=5`,
  );
  const exact = q.hits.find((h) => h.symbol?.toUpperCase() === symbol.toUpperCase()) ?? q.hits[0];
  if (!exact) throw new Error(`${symbol} is not a known human gene symbol`);
  return normalizeMyGene(exact, symbol);
}

// ------------------------------------------------------------------ Human Protein Atlas

export type HpaEntry = {
  mainLocations: string[];
  additionalLocations: string[];
  proteinClass: string[];
  evidence: string | null;
  tissueSpecificity: string | null;
  tissueDistribution: string | null;
  cellTypeSpecificity: string | null;
  /** Cell types where the RNA is enriched, with normalized counts. */
  cellTypeEnriched: { cellType: string; ncpm: number }[];
};

type HpaRaw = Record<string, unknown>;

function strList(v: unknown): string[] {
  if (Array.isArray(v)) return v.filter((x): x is string => typeof x === "string");
  return typeof v === "string" && v ? [v] : [];
}
function str(v: unknown): string | null {
  return typeof v === "string" && v ? v : null;
}

export function normalizeHpa(raw: HpaRaw): HpaEntry {
  const enriched = raw["RNA single cell type specific nCPM"];
  const cellTypeEnriched =
    enriched && typeof enriched === "object"
      ? Object.entries(enriched as Record<string, string | number>)
          .map(([cellType, v]) => ({ cellType, ncpm: Number(v) }))
          .filter((x) => Number.isFinite(x.ncpm))
          .sort((a, b) => b.ncpm - a.ncpm)
      : [];
  return {
    mainLocations: strList(raw["Subcellular main location"]),
    additionalLocations: strList(raw["Subcellular additional location"]),
    proteinClass: strList(raw["Protein class"]),
    evidence: str(raw.Evidence),
    tissueSpecificity: str(raw["RNA tissue specificity"]),
    tissueDistribution: str(raw["RNA tissue distribution"]),
    cellTypeSpecificity: str(raw["RNA single cell type specificity"]),
    cellTypeEnriched,
  };
}

export async function fetchHpa(ensembl: string): Promise<HpaEntry | null> {
  const res = await fetch(`https://www.proteinatlas.org/${encodeURIComponent(ensembl)}.json`);
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`proteinatlas.org answered ${res.status}`);
  return normalizeHpa((await res.json()) as HpaRaw);
}

// ------------------------------------------------------------------ UniProt

export type UniProtEntry = {
  accession: string;
  proteinName: string | null;
  /** Curated function paragraph. */
  functionText: string | null;
  /** Controlled-vocabulary locations, e.g. "Cell membrane", "Golgi apparatus". */
  locations: string[];
  length: number | null;
};

type UniProtRaw = {
  primaryAccession: string;
  proteinDescription?: { recommendedName?: { fullName?: { value: string } } };
  comments?: {
    commentType: string;
    texts?: { value: string }[];
    subcellularLocations?: { location: { value: string; id?: string } }[];
  }[];
  sequence?: { length: number };
};

export function normalizeUniProt(raw: UniProtRaw): UniProtEntry {
  const comments = raw.comments ?? [];
  const fn = comments.find((c) => c.commentType === "FUNCTION")?.texts?.[0]?.value ?? null;
  const locs = new Set<string>();
  for (const c of comments) {
    if (c.commentType !== "SUBCELLULAR LOCATION") continue;
    for (const l of c.subcellularLocations ?? []) locs.add(l.location.value);
  }
  return {
    accession: raw.primaryAccession,
    proteinName: raw.proteinDescription?.recommendedName?.fullName?.value ?? null,
    functionText: fn,
    locations: [...locs],
    length: raw.sequence?.length ?? null,
  };
}

export async function fetchUniProt(accession: string): Promise<UniProtEntry> {
  const raw = await getJson<UniProtRaw>(
    `https://rest.uniprot.org/uniprotkb/${encodeURIComponent(accession)}.json?fields=accession,protein_name,cc_function,cc_subcellular_location,length`,
  );
  return normalizeUniProt(raw);
}

// ------------------------------------------------------------------ GTEx

export type GtexTissue = {
  /** e.g. "Brain_Cortex" */
  id: string;
  /** Median gene TPM across donors. */
  median: number;
  ontologyId: string;
};

type GtexRef = { data: { gencodeId: string; geneSymbolUpper: string }[] };
type GtexMedian = {
  data: { tissueSiteDetailId: string; median: number; ontologyId: string; unit: string }[];
};

const GTEX = "https://gtexportal.org/api/v2";
/** gtex_v10 is annotated with GENCODE v39; the versioned id must match or the query is empty. */
const GTEX_DATASET = "gtex_v10";
const GTEX_GENCODE = "v39";

export async function fetchGtex(symbol: string): Promise<GtexTissue[] | null> {
  const ref = await getJson<GtexRef>(
    `${GTEX}/reference/gene?geneId=${encodeURIComponent(symbol)}&gencodeVersion=${GTEX_GENCODE}&genomeBuild=GRCh38%2Fhg38`,
  );
  const hit = ref.data.find((g) => g.geneSymbolUpper === symbol.toUpperCase());
  if (!hit) return null;
  const med = await getJson<GtexMedian>(
    `${GTEX}/expression/medianGeneExpression?gencodeId=${encodeURIComponent(hit.gencodeId)}&datasetId=${GTEX_DATASET}&itemsPerPage=100`,
  );
  return med.data.map((d) => ({
    id: d.tissueSiteDetailId,
    median: d.median,
    ontologyId: d.ontologyId,
  }));
}

/** Readable names for GTEx's tissueSiteDetailId values. */
const GTEX_LABELS: Record<string, string> = {
  Adipose_Subcutaneous: "Adipose, subcutaneous",
  Adipose_Visceral_Omentum: "Adipose, visceral",
  Adrenal_Gland: "Adrenal gland",
  Artery_Aorta: "Aorta",
  Artery_Coronary: "Coronary artery",
  Artery_Tibial: "Tibial artery",
  Bladder: "Bladder",
  Brain_Amygdala: "Brain, amygdala",
  Brain_Anterior_cingulate_cortex_BA24: "Brain, anterior cingulate cortex",
  Brain_Caudate_basal_ganglia: "Brain, caudate",
  Brain_Cerebellar_Hemisphere: "Brain, cerebellar hemisphere",
  Brain_Cerebellum: "Brain, cerebellum",
  Brain_Cortex: "Brain, cortex",
  Brain_Frontal_Cortex_BA9: "Brain, frontal cortex",
  Brain_Hippocampus: "Brain, hippocampus",
  Brain_Hypothalamus: "Brain, hypothalamus",
  Brain_Nucleus_accumbens_basal_ganglia: "Brain, nucleus accumbens",
  Brain_Putamen_basal_ganglia: "Brain, putamen",
  "Brain_Spinal_cord_cervical_c-1": "Spinal cord (cervical)",
  Brain_Substantia_nigra: "Brain, substantia nigra",
  Breast_Mammary_Tissue: "Breast",
  Cells_Cultured_fibroblasts: "Cultured fibroblasts",
  "Cells_EBV-transformed_lymphocytes": "EBV-transformed lymphocytes",
  Cervix_Ectocervix: "Cervix, ectocervix",
  Cervix_Endocervix: "Cervix, endocervix",
  Colon_Sigmoid: "Colon, sigmoid",
  Colon_Transverse: "Colon, transverse",
  Esophagus_Gastroesophageal_Junction: "Esophagus, gastroesophageal junction",
  Esophagus_Mucosa: "Esophagus, mucosa",
  Esophagus_Muscularis: "Esophagus, muscularis",
  Fallopian_Tube: "Fallopian tube",
  Heart_Atrial_Appendage: "Heart, atrial appendage",
  Heart_Left_Ventricle: "Heart, left ventricle",
  Kidney_Cortex: "Kidney, cortex",
  Kidney_Medulla: "Kidney, medulla",
  Liver: "Liver",
  Lung: "Lung",
  Minor_Salivary_Gland: "Minor salivary gland",
  Muscle_Skeletal: "Skeletal muscle",
  Nerve_Tibial: "Tibial nerve",
  Ovary: "Ovary",
  Pancreas: "Pancreas",
  Pituitary: "Pituitary",
  Prostate: "Prostate",
  Skin_Not_Sun_Exposed_Suprapubic: "Skin (not sun-exposed)",
  Skin_Sun_Exposed_Lower_leg: "Skin (sun-exposed)",
  Small_Intestine_Terminal_Ileum: "Small intestine",
  Spleen: "Spleen",
  Stomach: "Stomach",
  Testis: "Testis",
  Thyroid: "Thyroid",
  Uterus: "Uterus",
  Vagina: "Vagina",
  Whole_Blood: "Whole blood",
};

/** "Brain_Frontal_Cortex_BA9" -> "Brain, frontal cortex"; unknown ids are de-underscored. */
export function gtexTissueLabel(id: string): string {
  return GTEX_LABELS[id] ?? id.replaceAll("_", " ");
}

// ------------------------------------------------------------------ STRING

/** Version-pinned host, as STRING recommends for anything that is not a one-off. */
const STRING = "https://version-12-0.string-db.org";

export type StringPartner = { symbol: string; score: number };

type StringRaw = { preferredName_A: string; preferredName_B: string; score: number }[];

export async function fetchStringPartners(symbol: string, limit = 10): Promise<StringPartner[]> {
  const res = await fetch(
    `${STRING}/api/json/interaction_partners?identifiers=${encodeURIComponent(symbol)}&species=${HUMAN_TAXON}&limit=${limit}&caller_identity=cell-ledger`,
  );
  // STRING answers 400 for identifiers it cannot map (e.g. non-coding genes).
  if (!res.ok) return [];
  const rows = (await res.json()) as StringRaw;
  if (!Array.isArray(rows)) return [];
  const self = symbol.toUpperCase();
  return rows
    .map((r) => ({
      symbol: r.preferredName_A.toUpperCase() === self ? r.preferredName_B : r.preferredName_A,
      score: r.score,
    }))
    .sort((a, b) => b.score - a.score);
}

export function stringNetworkImageUrl(symbol: string): string {
  const q = new URLSearchParams({
    identifiers: symbol,
    species: String(HUMAN_TAXON),
    add_white_nodes: "10",
    network_flavor: "confidence",
    hide_disconnected_nodes: "1",
    caller_identity: "cell-ledger",
  });
  return `${STRING}/api/svg/network?${q}`;
}

export function stringPageUrl(symbol: string): string {
  return `https://string-db.org/network/${HUMAN_TAXON}.${encodeURIComponent(symbol)}`;
}

// ------------------------------------------------------------------ AlphaFold DB

export type AlphaFoldModel = {
  entryId: string;
  pdbUrl: string;
  cifUrl: string;
  /** Mean pLDDT over the chain, 0 to 100. */
  meanPlddt: number;
  fractionConfident: number;
  fractionVeryHigh: number;
  fractionLow: number;
  fractionVeryLow: number;
  length: number;
};

type AlphaFoldRaw = {
  entryId: string;
  pdbUrl: string;
  cifUrl: string;
  globalMetricValue: number;
  fractionPlddtConfident: number;
  fractionPlddtVeryHigh: number;
  fractionPlddtLow: number;
  fractionPlddtVeryLow: number;
  uniprotEnd: number;
};

export async function fetchAlphaFold(accession: string): Promise<AlphaFoldModel | null> {
  const res = await fetch(
    `https://alphafold.ebi.ac.uk/api/prediction/${encodeURIComponent(accession)}`,
  );
  if (res.status === 404) return null;
  if (!res.ok) throw new Error(`alphafold.ebi.ac.uk answered ${res.status}`);
  const rows = (await res.json()) as AlphaFoldRaw[];
  const r = rows[0];
  if (!r) return null;
  return {
    entryId: r.entryId,
    pdbUrl: r.pdbUrl,
    cifUrl: r.cifUrl,
    meanPlddt: r.globalMetricValue,
    fractionConfident: r.fractionPlddtConfident,
    fractionVeryHigh: r.fractionPlddtVeryHigh,
    fractionLow: r.fractionPlddtLow,
    fractionVeryLow: r.fractionPlddtVeryLow,
    length: r.uniprotEnd,
  };
}

export function alphaFoldPageUrl(accession: string): string {
  return `https://alphafold.ebi.ac.uk/entry/${encodeURIComponent(accession)}`;
}

/** The AlphaFold DB confidence palette, by pLDDT band. */
export function plddtColor(plddt: number): string {
  if (plddt >= 90) return "#0053d6";
  if (plddt >= 70) return "#65cbf3";
  if (plddt >= 50) return "#ffdb13";
  return "#ff7d45";
}

export const PLDDT_BANDS: { label: string; color: string; range: string }[] = [
  { label: "Very high", color: plddtColor(95), range: "pLDDT > 90" },
  { label: "Confident", color: plddtColor(80), range: "70 – 90" },
  { label: "Low", color: plddtColor(60), range: "50 – 70" },
  { label: "Very low", color: plddtColor(30), range: "< 50" },
];

// ------------------------------------------------------------------ links

export function ncbiGeneUrl(entrez: string): string {
  return `https://www.ncbi.nlm.nih.gov/gene/${encodeURIComponent(entrez)}`;
}
export function hpaGeneUrl(ensembl: string, symbol: string): string {
  return `https://www.proteinatlas.org/${encodeURIComponent(ensembl)}-${encodeURIComponent(symbol)}`;
}
export function uniprotUrl(accession: string): string {
  return `https://www.uniprot.org/uniprotkb/${encodeURIComponent(accession)}/entry`;
}
export function gtexGeneUrl(symbol: string): string {
  return `https://gtexportal.org/home/gene/${encodeURIComponent(symbol)}`;
}

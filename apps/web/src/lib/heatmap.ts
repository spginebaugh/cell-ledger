/** The expression heatmap the pipeline writes for the browser (heatmap.json.gz), decoded. */
import { isGzip } from "./volcano";

export type HeatmapGene = {
  gene_id: string;
  symbol: string | null;
  log2fc: number;
  padj: number;
};

export type HeatmapSample = { id: string; arm: string };

export type HeatmapTable = {
  nGenes: number;
  nSamples: number;
  alpha: number;
  lfcThreshold: number;
  genes: HeatmapGene[];
  samples: HeatmapSample[];
  /** gene indices in clustered order */
  rowOrder: number[];
  /** sample indices in clustered order */
  colOrder: number[];
  /** z[gene][sample] */
  z: Float32Array[];
  /** log2(normalized + 1)[gene][sample] */
  log2: Float32Array[];
};

type Raw = {
  n_genes: number;
  n_samples: number;
  alpha: number;
  lfc_threshold: number;
  genes: HeatmapGene[];
  samples: HeatmapSample[];
  row_order: number[];
  col_order: number[];
  z: number[][];
  log2: number[][];
};

export async function decodeHeatmap(buffer: ArrayBuffer): Promise<HeatmapTable> {
  const bytes = new Uint8Array(buffer);
  let text: string;
  if (isGzip(bytes)) {
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes);
  }
  return fromRawHeatmap(JSON.parse(text) as Raw);
}

export function fromRawHeatmap(raw: Raw): HeatmapTable {
  return {
    nGenes: raw.n_genes,
    nSamples: raw.n_samples,
    alpha: raw.alpha,
    lfcThreshold: raw.lfc_threshold,
    genes: raw.genes,
    samples: raw.samples,
    rowOrder: raw.row_order,
    colOrder: raw.col_order,
    z: raw.z.map((r) => Float32Array.from(r)),
    log2: raw.log2.map((r) => Float32Array.from(r)),
  };
}

/** How well blind clustering recovered the arms: the share of adjacent sample pairs (in
 * clustered order) that share an arm, from 0.5 (shuffled) to 1 (perfectly split). */
export function armPurity(t: HeatmapTable): number | null {
  if (t.nSamples < 2) return null;
  let same = 0;
  for (let k = 1; k < t.colOrder.length; k++) {
    if (t.samples[t.colOrder[k]].arm === t.samples[t.colOrder[k - 1]].arm) same++;
  }
  return same / (t.colOrder.length - 1);
}

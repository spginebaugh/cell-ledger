/** The GSEA file the pipeline writes for the browser (gsea.json.gz): the ranked gene list and,
 * for each reported set, where its genes fall in it. The running score is recomputed here. */
import { isGzip } from "./volcano";

export type GseaTerm = { hits: number[]; es: number; peak: number };

export type GseaTable = {
  n: number;
  /** symbols in descending order of the ranking metric */
  ranked: string[];
  /** the ranking metric (DESeq2 Wald statistic), descending */
  metric: Float64Array;
  terms: Record<string, GseaTerm>;
  /** first rank whose metric is below zero: where "up in case" turns into "up in control" */
  zeroCross: number;
};

type Raw = {
  n: number;
  ranked: string[];
  metric: number[];
  terms: Record<string, GseaTerm>;
};

export async function decodeGsea(buffer: ArrayBuffer): Promise<GseaTable> {
  const bytes = new Uint8Array(buffer);
  let text: string;
  if (isGzip(bytes)) {
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes);
  }
  return fromRawGsea(JSON.parse(text) as Raw);
}

export function fromRawGsea(raw: Raw): GseaTable {
  const metric = Float64Array.from(raw.metric);
  let zeroCross = metric.length;
  for (let i = 0; i < metric.length; i++) {
    if (metric[i] < 0) {
      zeroCross = i;
      break;
    }
  }
  return { n: raw.n, ranked: raw.ranked, metric, terms: raw.terms, zeroCross };
}

export type RunningScore = {
  /** running score at every rank */
  res: Float64Array;
  /** rank of the extreme (the enrichment score) */
  peak: number;
  es: number;
  /** hit ranks in the leading edge: before the peak for a positive score, after it otherwise */
  leading: number[];
};

/** GSEA's weighted (p = 1) running score: up by |metric| / Σ|metric over hits| at a hit, down
 * by 1 / (N − hits) elsewhere. Reproduces gseapy's curve and enrichment score. */
export function runningScore(t: GseaTable, hits: number[]): RunningScore {
  const n = t.n;
  const isHit = new Uint8Array(n);
  let nr = 0;
  for (const h of hits) {
    isHit[h] = 1;
    nr += Math.abs(t.metric[h]);
  }
  const res = new Float64Array(n);
  const miss = hits.length < n ? 1 / (n - hits.length) : 0;
  let acc = 0;
  let peak = 0;
  for (let i = 0; i < n; i++) {
    acc += isHit[i] ? (nr > 0 ? Math.abs(t.metric[i]) / nr : 0) : -miss;
    res[i] = acc;
    if (Math.abs(acc) > Math.abs(res[peak])) peak = i;
  }
  const es = res[peak];
  const leading = es >= 0 ? hits.filter((h) => h <= peak) : hits.filter((h) => h >= peak);
  return { res, peak, es, leading };
}

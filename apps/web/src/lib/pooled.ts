/** The cross-dataset gene table the comparison writes for the browser (pooled_genes.json.gz),
 * decoded. One row per pooled gene with every dataset's own estimate beside the pooled one.
 * Values arrive quantised (fold changes and SEs to 0.01, -log10 padj to 0.1). */

import { isGzip } from "./volcano";

export type PooledMember = {
  label: string;
  gse: string;
  /** contributes to the pooled estimate; a set-aside dataset is drawn apart from the pool */
  pooled: boolean;
  flags: string[];
  nSamples: number;
};

export type PooledTable = {
  n: number;
  alpha: number;
  lfcThreshold: number;
  minStudies: number;
  members: PooledMember[];
  geneId: string[];
  symbol: (string | null)[];
  /** pooled log2 fold change */
  log2fc: Float32Array;
  /** -log10 pooled padj, NaN when not reported; pinned at 300 */
  negLog: Float32Array;
  nTested: Uint8Array;
  /** datasets whose sign matches the pooled direction */
  nAgree: Uint8Array;
  /** datasets significant in the pooled direction */
  nSig: Uint8Array;
  robust: Uint8Array;
  /** per member: that dataset's own log2FC per gene, NaN where untested */
  memberLfc: Float32Array[];
  memberSe: Float32Array[];
  /** per member: 1 where that dataset called the gene significant (its own padj < alpha) */
  memberSig: Uint8Array[];
};

type RawMember = {
  label: string;
  gse: string;
  pooled: boolean;
  flags: string[];
  n_samples: number;
};

export type RawPooled = {
  n: number;
  alpha: number;
  lfc_threshold: number;
  min_studies: number;
  lfc_scale: number;
  nlp_scale: number;
  members: RawMember[];
  gene_id: string[];
  symbol: (string | null)[];
  log2fc: (number | null)[];
  nlp: (number | null)[];
  n_tested: number[];
  n_agree: number[];
  n_sig: number[];
  robust: number[];
  member_lfc: (number | null)[][];
  member_se: (number | null)[][];
  member_sig: number[][];
};

export async function decodePooled(buffer: ArrayBuffer): Promise<PooledTable> {
  const bytes = new Uint8Array(buffer);
  let text: string;
  if (isGzip(bytes)) {
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes);
  }
  return fromRawPooled(JSON.parse(text) as RawPooled);
}

export function fromRawPooled(raw: RawPooled): PooledTable {
  const n = raw.gene_id.length;
  const scaled = (col: (number | null)[], scale: number) => {
    const a = new Float32Array(n);
    for (let i = 0; i < n; i++) {
      const v = col[i];
      a[i] = v === null || v === undefined ? Number.NaN : v / scale;
    }
    return a;
  };
  const bytes = (col: number[]) => Uint8Array.from(col);
  return {
    n,
    alpha: raw.alpha,
    lfcThreshold: raw.lfc_threshold,
    minStudies: raw.min_studies,
    members: raw.members.map((m) => ({
      label: m.label,
      gse: m.gse,
      pooled: m.pooled,
      flags: m.flags ?? [],
      nSamples: m.n_samples,
    })),
    geneId: raw.gene_id,
    symbol: raw.symbol,
    log2fc: scaled(raw.log2fc, raw.lfc_scale),
    negLog: scaled(raw.nlp, raw.nlp_scale),
    nTested: bytes(raw.n_tested),
    nAgree: bytes(raw.n_agree),
    nSig: bytes(raw.n_sig),
    robust: bytes(raw.robust),
    memberLfc: raw.member_lfc.map((c) => scaled(c, raw.lfc_scale)),
    memberSe: raw.member_se.map((c) => scaled(c, raw.lfc_scale)),
    memberSig: raw.member_sig.map(bytes),
  };
}

/** Per dataset, the share of robust genes it tested whose sign matches the pooled direction.
 * This is the number under each column of the agreement wall. */
export function memberAgreement(t: PooledTable): (number | null)[] {
  return t.members.map((_, j) => {
    const lfc = t.memberLfc[j];
    let tested = 0;
    let agree = 0;
    for (let i = 0; i < t.n; i++) {
      if (!t.robust[i]) continue;
      const v = lfc[i];
      if (Number.isNaN(v) || v === 0) continue;
      tested++;
      if (v > 0 === t.log2fc[i] > 0) agree++;
    }
    return tested === 0 ? null : agree / tested;
  });
}

/** Indices of robust genes, higher-in-case first, each block ordered by pooled effect so the
 * wall reads as two solid bands. */
export function wallOrder(t: PooledTable): number[] {
  const up: number[] = [];
  const down: number[] = [];
  for (let i = 0; i < t.n; i++) {
    if (!t.robust[i]) continue;
    (t.log2fc[i] > 0 ? up : down).push(i);
  }
  up.sort((a, b) => t.log2fc[b] - t.log2fc[a]);
  down.sort((a, b) => t.log2fc[a] - t.log2fc[b]);
  return [...up, ...down];
}

export type PooledCounts = { up: number; down: number; pooled: number };

/** Genes called at the thresholds, by pooled direction. */
export function countPooled(t: PooledTable, alpha: number, lfc: number): PooledCounts {
  let up = 0;
  let down = 0;
  const cut = -Math.log10(alpha);
  for (let i = 0; i < t.n; i++) {
    const nl = t.negLog[i];
    if (Number.isNaN(nl)) continue;
    if (nl >= cut && Math.abs(t.log2fc[i]) >= lfc) {
      if (t.log2fc[i] > 0) up++;
      else down++;
    }
  }
  return { up, down, pooled: t.n };
}

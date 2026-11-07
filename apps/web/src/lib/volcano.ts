/** The DE table the pipeline writes for the browser (volcano.json.gz), decoded. */
export type VolcanoTable = {
  n: number;
  alpha: number;
  lfcThreshold: number;
  geneId: string[];
  symbol: (string | null)[];
  baseMean: Float64Array;
  log2fc: Float64Array;
  /** NaN where DESeq2 reported no adjusted p (independent filtering). */
  padj: Float64Array;
  /** -log10(padj), NaN where padj is NaN. */
  negLog: Float64Array;
};

type Raw = {
  n: number;
  alpha: number;
  lfc_threshold: number;
  gene_id: string[];
  symbol: (string | null)[];
  base_mean: (number | null)[];
  log2fc: (number | null)[];
  padj: (number | null)[];
};

export function isGzip(bytes: Uint8Array): boolean {
  return bytes.length > 2 && bytes[0] === 0x1f && bytes[1] === 0x8b;
}

export async function decodeVolcano(buffer: ArrayBuffer): Promise<VolcanoTable> {
  const bytes = new Uint8Array(buffer);
  let text: string;
  if (isGzip(bytes)) {
    const ds = new DecompressionStream("gzip");
    const stream = new Blob([bytes]).stream().pipeThrough(ds);
    text = await new Response(stream).text();
  } else {
    text = new TextDecoder().decode(bytes);
  }
  return fromRaw(JSON.parse(text) as Raw);
}

export function fromRaw(raw: Raw): VolcanoTable {
  const n = raw.gene_id.length;
  const toArr = (col: (number | null)[]) => {
    const a = new Float64Array(n);
    for (let i = 0; i < n; i++) {
      const v = col[i];
      a[i] = v === null || v === undefined ? Number.NaN : v;
    }
    return a;
  };
  const padj = toArr(raw.padj);
  const negLog = new Float64Array(n);
  for (let i = 0; i < n; i++) {
    const p = padj[i];
    negLog[i] = Number.isNaN(p) ? Number.NaN : -Math.log10(Math.max(p, 1e-300));
  }
  return {
    n,
    alpha: raw.alpha,
    lfcThreshold: raw.lfc_threshold,
    geneId: raw.gene_id,
    symbol: raw.symbol,
    baseMean: toArr(raw.base_mean),
    log2fc: toArr(raw.log2fc),
    padj,
    negLog,
  };
}

export type SigCounts = { up: number; down: number; tested: number };

export function countSignificant(t: VolcanoTable, alpha: number, lfc: number): SigCounts {
  let up = 0;
  let down = 0;
  let tested = 0;
  for (let i = 0; i < t.n; i++) {
    const p = t.padj[i];
    if (Number.isNaN(p)) continue;
    tested++;
    if (p < alpha && Math.abs(t.log2fc[i]) >= lfc) {
      if (t.log2fc[i] > 0) up++;
      else down++;
    }
  }
  return { up, down, tested };
}

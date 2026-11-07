import type {
  ValidationComparison,
  ValidationDataset,
  ValidationResults,
} from "@/lib/validation-results";

export type LfcPoints = {
  n: number;
  /** the authors' log2 fold change */
  published: Float64Array;
  /** the pipeline's unshrunk log2 fold change */
  ours: Float64Array;
  /** gene symbol per point, "" when the annotation has none */
  symbols: string[];
};

/** Little-endian Int16 pairs in base64, quantised to 0.01, back to log2 fold changes. */
export function decodeLfc(b64: string): Float64Array {
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const out = new Float64Array(bytes.byteLength / 2);
  for (let i = 0; i < out.length; i++) out[i] = view.getInt16(i * 2, true) / 100;
  return out;
}

export function decodePoints(c: ValidationComparison): LfcPoints {
  const published = decodeLfc(c.px);
  const ours = decodeLfc(c.ox);
  const symbols = c.symbols.split("|");
  const n = Math.min(published.length, ours.length, symbols.length);
  return { n, published, ours, symbols };
}

export function comparisonsFor(results: ValidationResults, ds: ValidationDataset) {
  return results.comparisons.filter((c) => c.gse === ds.gse);
}

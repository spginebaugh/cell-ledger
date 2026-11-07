import type { DesignProposal, DiscoveryResult } from "@/api/generated/types.gen";

/** What the UI parks on the session row (PATCH /sessions/{id} state) so a reload restores it. */
export type UiState = {
  discovery?: DiscoveryResult | null;
  genes?: string[];
  selected?: string[];
  answers?: string;
  proposals?: Record<string, DesignProposal>;
};

export function readState(state: unknown): UiState {
  if (!state || typeof state !== "object") return {};
  return state as UiState;
}

/** Gene symbols mentioned in free text: upper-case tokens of 2–10 chars with a digit or ≥3 letters. */
export function guessGenes(text: string): string[] {
  const out = new Set<string>();
  for (const m of text.matchAll(/\b[A-Z][A-Z0-9]{1,9}\b/g)) {
    const t = m[0];
    if (/^(RNA|DNA|GEO|GSE|GSM|NCBI|VS|AND|OR|THE|IN|OF|A|IS|SEQ)$/.test(t)) continue;
    if (/\d/.test(t) || t.length >= 3) out.add(t);
  }
  return [...out];
}

export function slugify(s: string): string {
  return (
    s
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "_")
      .replace(/^_+|_+$/g, "")
      .slice(0, 60) || "comparison"
  );
}

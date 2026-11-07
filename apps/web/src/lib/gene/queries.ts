import { useQuery } from "@tanstack/react-query";
import {
  fetchAlphaFold,
  fetchGeneCore,
  fetchGtex,
  fetchHpa,
  fetchStringPartners,
  fetchUniProt,
} from "./sources";

/** Annotations never change within a session, so nothing here is ever refetched. The public
 * services answer 503 now and then, so transient failures are retried a few times. */
const forever = { staleTime: Number.POSITIVE_INFINITY, gcTime: 30 * 60_000, retry: 3 } as const;

export function useGeneCore(entrez: string | null, symbol: string | null) {
  return useQuery({
    queryKey: ["gene", "core", entrez ?? `symbol:${symbol?.toUpperCase()}`],
    queryFn: () => fetchGeneCore(entrez, symbol ?? ""),
    enabled: Boolean(entrez || symbol),
    ...forever,
  });
}

export function useHpa(ensembl: string | null | undefined) {
  return useQuery({
    queryKey: ["gene", "hpa", ensembl],
    queryFn: () => fetchHpa(ensembl as string),
    enabled: Boolean(ensembl),
    ...forever,
  });
}

export function useUniProt(accession: string | null | undefined) {
  return useQuery({
    queryKey: ["gene", "uniprot", accession],
    queryFn: () => fetchUniProt(accession as string),
    enabled: Boolean(accession),
    ...forever,
  });
}

export function useGtex(symbol: string | null) {
  return useQuery({
    queryKey: ["gene", "gtex", symbol],
    queryFn: () => fetchGtex(symbol as string),
    enabled: Boolean(symbol),
    ...forever,
  });
}

export function useStringPartners(symbol: string | null, enabled = true) {
  return useQuery({
    queryKey: ["gene", "string", symbol],
    queryFn: () => fetchStringPartners(symbol as string),
    enabled: Boolean(symbol) && enabled,
    ...forever,
  });
}

export function useAlphaFold(accession: string | null | undefined) {
  return useQuery({
    queryKey: ["gene", "alphafold", accession],
    queryFn: () => fetchAlphaFold(accession as string),
    enabled: Boolean(accession),
    ...forever,
  });
}

/** A vendored SVG from public/, as text, so it can be inlined and styled by element id. */
export function useSvgAsset(path: string) {
  return useQuery({
    queryKey: ["asset", path],
    queryFn: async () => {
      const res = await fetch(path);
      if (!res.ok) throw new Error(`could not load ${path}`);
      return res.text();
    },
    ...forever,
  });
}

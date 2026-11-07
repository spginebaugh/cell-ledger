import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  collectDatasets,
  createSession,
  getAgentTypes,
  getComparison,
  getRun,
  getSession,
  listComparisons,
  listDatasets,
  listRuns,
} from "@/api/generated/sdk.gen";
import type {
  ComparisonStatus,
  DatasetStatus,
  RunStatus,
  RunView,
} from "@/api/generated/types.gen";
import { unwrap } from "./api";

export const POLL_MS = 2000;

export const keys = {
  agent: ["agent"] as const,
  session: (id: string) => ["session", id] as const,
  datasets: (id: string) => ["session", id, "datasets"] as const,
  runs: (id: string) => ["session", id, "runs"] as const,
  runDetails: (id: string) => ["session", id, "run"] as const,
  run: (id: string, gse: string, contrast: string) =>
    [...keys.runDetails(id), gse, contrast] as const,
  comparisons: (id: string) => ["session", id, "comparisons"] as const,
  comparisonDetails: (id: string) => ["session", id, "comparison"] as const,
  comparison: (id: string, name: string) => [...keys.comparisonDetails(id), name] as const,
};

export function useAgentAvailable() {
  return useQuery({
    queryKey: keys.agent,
    queryFn: async () => unwrap(await getAgentTypes()).available,
    staleTime: 5 * 60_000,
  });
}

export function useSession(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.session(id),
    queryFn: async () => unwrap(await getSession({ path: { session_id: id } })),
    enabled,
    retry: (count, err) =>
      !(err && "status" in err && (err as { status: number }).status === 404) && count < 2,
  });
}

export function useCreateSession() {
  return useMutation({ mutationFn: async () => unwrap(await createSession()) });
}

/** ``poll`` keeps refetching while the page says so (the session view drives the whole
 * pipeline off these lists); otherwise a list polls only while one of its rows is in flight. */
export function useDatasets(id: string, enabled = true, poll = false) {
  return useQuery({
    queryKey: keys.datasets(id),
    queryFn: async () => unwrap(await listDatasets({ path: { session_id: id } })),
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as DatasetStatus[] | undefined;
      const busy = data?.some(
        (d) =>
          d.status === "pending" ||
          (d.status === "ready" &&
            (d.design_status === "pending" || d.design_status === "designing")),
      );
      return poll || busy ? POLL_MS : false;
    },
  });
}

export function useCollect(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (gses: string[]) =>
      unwrap(await collectDatasets({ path: { session_id: id }, body: { gses } })),
    onSuccess: (data) => qc.setQueryData(keys.datasets(id), data),
  });
}

export function useRuns(id: string, enabled = true, poll = false) {
  return useQuery({
    queryKey: keys.runs(id),
    queryFn: async () => unwrap(await listRuns({ path: { session_id: id } })),
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as RunStatus[] | undefined;
      return poll || data?.some((r) => r.status === "running") ? POLL_MS : false;
    },
  });
}

export function useRun(id: string, gse: string, contrast: string) {
  return useQuery({
    queryKey: keys.run(id, gse, contrast),
    queryFn: async () => unwrap(await getRun({ path: { session_id: id, gse, contrast } })),
    refetchInterval: (q) =>
      (q.state.data as RunView | undefined)?.status === "running" ? POLL_MS : false,
    staleTime: (q) =>
      (q.state.data as RunView | undefined)?.status === "running" ? 0 : Number.POSITIVE_INFINITY,
  });
}

export function useComparisons(id: string, enabled = true, poll = false) {
  return useQuery({
    queryKey: keys.comparisons(id),
    queryFn: async () => unwrap(await listComparisons({ path: { session_id: id } })),
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as ComparisonStatus[] | undefined;
      return poll || data?.some((c) => c.status === "running") ? POLL_MS : false;
    },
  });
}

export function useComparison(id: string, name: string) {
  return useQuery({
    queryKey: keys.comparison(id, name),
    queryFn: async () => unwrap(await getComparison({ path: { session_id: id, name } })),
    refetchInterval: (q) => (q.state.data?.status === "running" ? POLL_MS : false),
    staleTime: (q) => (q.state.data?.status === "running" ? 0 : Number.POSITIVE_INFINITY),
  });
}

/** Fetch a stored file through its signed URL (no auth, straight from Storage). */
export async function fetchFileText(url: string): Promise<string> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`download failed (${r.status})`);
  return r.text();
}

export async function fetchFileBytes(url: string): Promise<ArrayBuffer> {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`download failed (${r.status})`);
  return r.arrayBuffer();
}

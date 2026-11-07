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
  startComparison,
  startRun,
  updateSession,
  verifyGeoSeries,
} from "@/api/generated/sdk.gen";
import type {
  CompareRequest,
  ComparisonStatus,
  DatasetStatus,
  RunRequest,
  RunStatus,
  RunView,
  SessionInfo,
} from "@/api/generated/types.gen";
import { unwrap } from "./api";

export const POLL_MS = 2000;

export const keys = {
  agent: ["agent"] as const,
  session: (id: string) => ["session", id] as const,
  datasets: (id: string) => ["session", id, "datasets"] as const,
  runs: (id: string) => ["session", id, "runs"] as const,
  run: (id: string, gse: string, contrast: string) =>
    ["session", id, "run", gse, contrast] as const,
  comparisons: (id: string) => ["session", id, "comparisons"] as const,
  comparison: (id: string, name: string) => ["session", id, "comparison", name] as const,
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

export function useUpdateSession(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: {
      question?: string | null;
      state?: Record<string, unknown> | null;
    }) => unwrap(await updateSession({ path: { session_id: id }, body })),
    onSuccess: (info: SessionInfo) => qc.setQueryData(keys.session(id), info),
  });
}

export function useCreateSession() {
  return useMutation({ mutationFn: async () => unwrap(await createSession()) });
}

export function useDatasets(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.datasets(id),
    queryFn: async () => unwrap(await listDatasets({ path: { session_id: id } })),
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as DatasetStatus[] | undefined;
      return data?.some((d) => d.status === "pending") ? POLL_MS : false;
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

export function useRuns(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.runs(id),
    queryFn: async () => unwrap(await listRuns({ path: { session_id: id } })),
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as RunStatus[] | undefined;
      return data?.some((r) => r.status === "running") ? POLL_MS : false;
    },
  });
}

export function useStartRun(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: RunRequest) =>
      unwrap(await startRun({ path: { session_id: id }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.runs(id) }),
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

export function useComparisons(id: string, enabled = true) {
  return useQuery({
    queryKey: keys.comparisons(id),
    queryFn: async () => unwrap(await listComparisons({ path: { session_id: id } })),
    enabled,
    refetchInterval: (q) => {
      const data = q.state.data as ComparisonStatus[] | undefined;
      return data?.some((c) => c.status === "running") ? POLL_MS : false;
    },
  });
}

export function useStartComparison(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (body: CompareRequest) =>
      unwrap(await startComparison({ path: { session_id: id }, body })),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.comparisons(id) }),
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

export function useVerifyGeo() {
  return useMutation({
    mutationFn: async (gses: string[]) => unwrap(await verifyGeoSeries({ body: { gses } })),
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

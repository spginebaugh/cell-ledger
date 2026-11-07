import { Link } from "@tanstack/react-router";
import { ArrowRight, Loader2 } from "lucide-react";
import type { ComparisonStatus } from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Card, Empty } from "@/components/ui/card";
import { statusLabel, statusTone } from "@/lib/format";

/** The comparison the pipeline started once every run was done; there is at most one. */
export function ComparisonsSection({
  sessionId,
  comparisons,
  completeRuns,
  settled,
}: {
  sessionId: string;
  comparisons: ComparisonStatus[];
  completeRuns: number;
  settled: boolean;
}) {
  if (comparisons.length === 0) {
    return (
      <Empty title={settled ? "No comparison" : "No comparison yet"}>
        {settled
          ? completeRuns === 1
            ? "Only one dataset produced a result, so there is nothing to pool; that run is the answer."
            : "No dataset produced a result to pool."
          : "Once every run is done, the complete ones are pooled to see what replicates."}
      </Empty>
    );
  }
  return (
    <div className="space-y-3">
      {comparisons.map((c) => (
        <Card key={c.name} className="flex flex-wrap items-center justify-between gap-3 p-4">
          <div>
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[14px] font-medium">{c.name}</span>
              <Badge tone={statusTone(c.status)}>
                {c.status === "running" && <Loader2 size={12} className="animate-spin" />}
                {statusLabel(c.status)}
              </Badge>
            </div>
            <p className="mt-1 text-sm text-ink-2">
              {c.request.members.length} datasets pooled
              {c.report?.genes && <> · {c.report.genes.n_robust} robust genes</>}
            </p>
            {c.error && c.status === "failed" && (
              <p className="mt-1 text-[13px] text-danger">{c.error}</p>
            )}
          </div>
          {c.status !== "running" && (
            <Link
              to="/s/$sessionId/compare/$name"
              params={{ sessionId, name: c.name }}
              className="inline-flex items-center gap-1 rounded-md border border-line-2 px-3 py-1.5 text-sm font-medium hover:bg-surface-2"
            >
              Open the comparison <ArrowRight size={14} />
            </Link>
          )}
        </Card>
      ))}
    </div>
  );
}

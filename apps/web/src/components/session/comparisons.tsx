import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import type { ComparisonStatus } from "@/api/generated/types.gen";
import { StatusChip } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Empty, Panel } from "@/components/ui/card";
import { cn } from "@/lib/utils";

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
        <Panel key={c.name} className="flex flex-wrap items-center justify-between gap-3">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <span className="font-mono text-[13px] font-medium text-accent-ink">{c.name}</span>
              <StatusChip status={c.status} busy={c.status === "running"} />
            </div>
            <p className="num mt-1 text-[13px] text-ink-2">
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
              className={cn(buttonVariants({ variant: "secondary", size: "sm" }), "no-underline")}
            >
              Open the comparison <ArrowRight size={14} />
            </Link>
          )}
        </Panel>
      ))}
    </div>
  );
}

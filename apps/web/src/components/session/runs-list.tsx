import { Link } from "@tanstack/react-router";
import { ArrowRight } from "lucide-react";
import type { RunStatus } from "@/api/generated/types.gen";
import { LiveStepper } from "@/components/run/steps";
import { Badge } from "@/components/ui/badge";
import { Card, Empty } from "@/components/ui/card";
import { fmtInt, statusLabel, statusTone, verdictGlyph, verdictTone } from "@/lib/format";
import { cn } from "@/lib/utils";

export function RunsList({ sessionId, runs }: { sessionId: string; runs: RunStatus[] }) {
  if (runs.length === 0) {
    return (
      <Empty title="No runs yet">
        A run starts on its own as soon as a dataset above has its contrast.
      </Empty>
    );
  }
  return (
    <div className="space-y-3">
      {runs.map((r) => {
        const rep = r.report;
        const blockers = rep?.blockers ?? [];
        const quals = rep?.qualifications ?? [];
        const lookups = rep?.gene_lookup ?? [];
        return (
          <Card key={`${r.gse}-${r.contrast}`} className="p-4">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="accession font-medium">{r.gse}</span>
                  <span className="font-mono text-[13px] text-ink-2">{r.contrast}</span>
                  <Badge tone={statusTone(r.status)}>{statusLabel(r.status)}</Badge>
                </div>
                {rep && (
                  <p className="mt-1 text-sm text-ink-2">
                    {rep.contrast.case_label} <span className="text-ink-3">vs</span>{" "}
                    {rep.contrast.control_label}
                  </p>
                )}
                {rep?.de && (
                  <p className="num mt-1 text-[13px] text-ink-2">
                    {fmtInt(rep.de.summary.n_sig)} genes differ ·{" "}
                    <span className="text-case">{fmtInt(rep.de.summary.n_up)} ▲</span> ·{" "}
                    <span className="text-control">{fmtInt(rep.de.summary.n_down)} ▼</span>
                    {blockers.length > 0 && (
                      <>
                        {" "}
                        · {blockers.length} blocker{blockers.length === 1 ? "" : "s"}
                      </>
                    )}
                    {quals.length > 0 && (
                      <>
                        {" "}
                        · {quals.length} caveat{quals.length === 1 ? "" : "s"}
                      </>
                    )}
                  </p>
                )}
                {rep && lookups.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {lookups.map((g) => (
                      <span
                        key={g.query}
                        className={cn(
                          "inline-flex items-center gap-1 rounded-sm bg-surface-2 px-1.5 py-0.5 text-[12px]",
                          verdictTone(g.verdict) === "case" && "text-case",
                          verdictTone(g.verdict) === "control" && "text-control",
                          verdictTone(g.verdict) === "muted" && "text-ink-3",
                        )}
                      >
                        <span aria-hidden>{verdictGlyph(g.verdict)}</span>
                        {g.symbol ?? g.query}
                      </span>
                    ))}
                  </div>
                )}
                {r.status === "failed" && r.error && (
                  <p className="mt-1 text-[13px] text-danger">{r.error}</p>
                )}
                {rep && rep.status !== "complete" && blockers.length > 0 && (
                  <p className="mt-1 text-[13px] text-ink-2">{blockers[0]}</p>
                )}
              </div>
              {r.status !== "running" && (
                <Link
                  to="/s/$sessionId/runs/$gse/$contrast"
                  params={{ sessionId, gse: r.gse, contrast: r.contrast }}
                  className="inline-flex items-center gap-1 rounded-md border border-line-2 px-3 py-1.5 text-sm font-medium hover:bg-surface-2"
                >
                  Open the result <ArrowRight size={14} />
                </Link>
              )}
            </div>
            {r.status === "running" && (
              <div className="mt-3 max-w-md">
                <LiveStepper progress={r.progress} startedAt={r.started_at} compact />
              </div>
            )}
          </Card>
        );
      })}
    </div>
  );
}

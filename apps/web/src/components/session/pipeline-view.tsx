import { Link } from "@tanstack/react-router";
import { ArrowRight, Check, Loader2 } from "lucide-react";
import type {
  ComparisonStatus,
  DatasetStatus,
  DesignProposal,
  RunStatus,
} from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Card, Details, Notice } from "@/components/ui/card";
import { fmtNum, humanExclusion, statusLabel, statusTone } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Stage = "collecting" | "designing" | "running" | "comparing" | "done";

const inDesign = (d: DatasetStatus) =>
  d.design_status === "pending" || d.design_status === "designing";

const STAGES: { key: Stage; label: string; doing: string }[] = [
  { key: "collecting", label: "Collect", doing: "Downloading counts and sample records" },
  { key: "designing", label: "Design", doing: "Choosing each dataset's contrast" },
  { key: "running", label: "Run", doing: "Fitting the differential expression" },
  { key: "comparing", label: "Compare", doing: "Pooling the results across datasets" },
  { key: "done", label: "Done", doing: "Everything that could run has run" },
];

/** Where the session is, read off the three lists the page already polls. */
export function deriveStage(
  datasets: DatasetStatus[],
  runs: RunStatus[],
  comparisons: ComparisonStatus[],
): { stage: Stage; settled: boolean; completeDatasets: number } {
  const completeDatasets = new Set(runs.filter((r) => r.status === "complete").map((r) => r.gse))
    .size;
  if (datasets.some((d) => d.status === "pending"))
    return { stage: "collecting", settled: false, completeDatasets };
  if (datasets.some((d) => d.status === "ready" && inDesign(d)))
    return { stage: "designing", settled: false, completeDatasets };
  if (runs.some((r) => r.status === "running"))
    return { stage: "running", settled: false, completeDatasets };
  if (comparisons.some((c) => c.status === "running"))
    return { stage: "comparing", settled: false, completeDatasets };
  // Every run is done and two datasets completed: the comparison is about to start.
  if (completeDatasets >= 2 && comparisons.length === 0)
    return { stage: "comparing", settled: false, completeDatasets };
  return { stage: "done", settled: true, completeDatasets };
}

export function PipelineStepper({ stage }: { stage: Stage }) {
  const at = STAGES.findIndex((s) => s.key === stage);
  return (
    <ol className="flex flex-wrap gap-x-6 gap-y-2" aria-label="Pipeline progress">
      {STAGES.map((s, i) => {
        const done = i < at || (stage === "done" && i === at);
        const current = i === at && stage !== "done";
        return (
          <li
            key={s.key}
            aria-current={current ? "step" : undefined}
            className={cn(
              "flex items-center gap-1.5 text-sm",
              done ? "text-ink" : current ? "font-medium text-ink" : "text-ink-3",
            )}
          >
            {done ? (
              <Check size={14} className="text-case" />
            ) : current ? (
              <Loader2 size={14} className="animate-spin text-case" />
            ) : (
              <span className="inline-block h-3.5 w-3.5 rounded-full border border-line-2" />
            )}
            {s.label}
            {current && (
              <span className="hidden text-ink-2 sm:inline"> · {s.doing.toLowerCase()}</span>
            )}
          </li>
        );
      })}
    </ol>
  );
}

function designLabel(d: DatasetStatus): {
  text: string;
  tone: "ok" | "neutral" | "amber" | "danger";
} {
  switch (d.design_status) {
    case "designed":
      return { text: "Contrast chosen", tone: "ok" };
    case "skipped":
      return { text: "Set aside", tone: "amber" };
    case "failed":
      return { text: "No design", tone: "danger" };
    case "designing":
      return { text: "Choosing the contrast", tone: "neutral" };
    default:
      return { text: "Waiting to be designed", tone: "neutral" };
  }
}

/** One dataset from download to its run, with the decisions the agent made on the way. */
export function DatasetRow({
  sessionId,
  dataset,
  run,
}: {
  sessionId: string;
  dataset: DatasetStatus;
  run: RunStatus | undefined;
}) {
  const r = dataset.record;
  const total = r?.samples?.length ?? 0;
  const proposal = dataset.proposal ?? undefined;
  const contrast = proposal?.design.contrasts[0];
  const ready = dataset.status === "ready";
  const design = designLabel(dataset);
  return (
    <Card className="p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="accession text-[15px] font-medium">{dataset.gse}</span>
            <Badge tone={statusTone(dataset.status)}>
              {dataset.status === "pending" && <Loader2 size={12} className="animate-spin" />}
              {statusLabel(dataset.status)}
            </Badge>
            {ready && (
              <Badge tone={design.tone}>
                {inDesign(dataset) && <Loader2 size={12} className="animate-spin" />}
                {design.text}
              </Badge>
            )}
            {run && <Badge tone={statusTone(run.status)}>run {statusLabel(run.status)}</Badge>}
          </div>
          {r?.title && <h3 className="mt-1.5 leading-snug">{r.title}</h3>}
          {r && ready && (
            <p className="num mt-1 text-[13px] text-ink-2">
              {r.n_eligible} of {total} samples are human bulk RNA-seq with counts
              {" · "}
              <a
                className="underline-offset-2 hover:underline"
                href={`https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${dataset.gse}`}
                target="_blank"
                rel="noreferrer"
              >
                GEO
              </a>
            </p>
          )}
          {dataset.status === "pending" && (
            <p className="mt-1 text-[13px] text-ink-2">
              Downloading the counts matrix and sample records from NCBI…
            </p>
          )}
          {dataset.status === "excluded" && r && (
            <p className="mt-1 text-[13px] text-ink-2">
              Excluded: {(r.exclusions ?? []).map(humanExclusion).join("; ")}.
            </p>
          )}
          {dataset.status === "failed" && (
            <p className="mt-1 text-[13px] text-danger">
              Download failed: {dataset.error ?? "unknown error"}
            </p>
          )}
        </div>
        {run && run.status !== "running" && (
          <Link
            to="/s/$sessionId/runs/$gse/$contrast"
            params={{ sessionId, gse: run.gse, contrast: run.contrast }}
            className="inline-flex shrink-0 items-center gap-1 rounded-md border border-line-2 px-3 py-1.5 text-sm font-medium hover:bg-surface-2"
          >
            Open the result <ArrowRight size={14} />
          </Link>
        )}
      </div>

      {ready && inDesign(dataset) && (
        <p className="mt-3 text-sm text-ink-2">
          The specialist is labelling every sample from its GEO record and choosing the one
          comparison that answers the question. Nothing to do here; this page updates itself.
        </p>
      )}
      {dataset.design_status === "failed" && (
        <div className="mt-3">
          <Notice tone="danger" title="This dataset could not be designed">
            {dataset.design_error ?? "unknown error"}
          </Notice>
        </div>
      )}
      {dataset.design_status === "skipped" && (
        <div className="mt-3">
          <Notice tone="amber" title="Set aside: the contrast cannot be run">
            {dataset.design_error ?? "not runnable"}
          </Notice>
        </div>
      )}
      {contrast && (
        <div className="mt-4 grid gap-3 sm:grid-cols-2">
          <div className="border-l-[3px] border-case pl-3">
            <div className="text-[13px] text-ink-2">Case · {contrast.case_gsms.length} samples</div>
            <div className="font-medium">{contrast.case_label}</div>
          </div>
          <div className="border-l-[3px] border-control pl-3">
            <div className="text-[13px] text-ink-2">
              Control · {contrast.control_gsms.length} samples
            </div>
            <div className="font-medium">{contrast.control_label}</div>
          </div>
        </div>
      )}
      {contrast && (contrast.blocking || contrast.rationale) && (
        <p className="mt-3 text-sm text-ink-2">
          {contrast.blocking && (
            <>
              Paired by <span className="font-medium text-ink">{contrast.blocking}</span>.{" "}
            </>
          )}
          {contrast.rationale}
          {contrast.confidence != null && (
            <span className="text-ink-3"> · confidence {fmtNum(contrast.confidence, 2)}</span>
          )}
        </p>
      )}
      {proposal && (
        <div className="mt-3">
          <Decisions proposal={proposal} />
        </div>
      )}
    </Card>
  );
}

/** What the agent decided on its own, so the only review there is can happen here. */
export function Decisions({
  proposal,
  defaultOpen,
}: {
  proposal: DesignProposal;
  defaultOpen?: boolean;
}) {
  const decisions = proposal.decisions ?? [];
  const quals = proposal.qualifications ?? [];
  const errors = proposal.validation_errors ?? [];
  const n = decisions.length + quals.length + errors.length;
  if (n === 0 && !proposal.notes) return null;
  return (
    <Details
      summary={`How the contrast was decided${n ? ` (${n} note${n === 1 ? "" : "s"})` : ""}`}
      defaultOpen={defaultOpen}
    >
      <div className="space-y-3 text-sm">
        {proposal.notes && <p className="text-ink-2">{proposal.notes}</p>}
        {decisions.length > 0 && (
          <div>
            <div className="text-[13px] font-medium text-ink-2">Decisions made for you</div>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {decisions.map((d) => (
                <li key={d}>{d}</li>
              ))}
            </ul>
          </div>
        )}
        {quals.length > 0 && (
          <div>
            <div className="text-[13px] font-medium text-amber">
              Read the result with these caveats
            </div>
            <ul className="mt-1 list-disc space-y-1 pl-5">
              {quals.map((q) => (
                <li key={q}>{q}</li>
              ))}
            </ul>
          </div>
        )}
        {errors.length > 0 && (
          <div>
            <div className="text-[13px] font-medium text-ink-2">
              {errors.length} label{errors.length === 1 ? "" : "s"} the GEO record could not back,
              dropped
            </div>
            <ul className="mt-1 list-disc space-y-1 pl-5 text-ink-2">
              {errors.slice(0, 8).map((e) => (
                <li key={e}>{e}</li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </Details>
  );
}

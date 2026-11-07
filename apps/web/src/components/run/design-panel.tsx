import { ArrowUpRight } from "lucide-react";
import type { AnalysisReport, DesignProposal } from "@/api/generated/types.gen";
import { ColHead, Panel, Tag } from "@/components/ui/card";
import { fmtInt } from "@/lib/format";

function Arm({
  tone,
  label,
  proposed,
  fitted,
}: {
  tone: "case" | "control";
  label: string;
  proposed: number;
  fitted: number | null;
}) {
  const dropped = fitted == null ? 0 : proposed - fitted;
  return (
    <div
      className={
        tone === "case" ? "border-l-[3px] border-case pl-3" : "border-l-[3px] border-control pl-3"
      }
    >
      <div className="num flex items-center gap-2 text-[12px] text-ink-2">
        <Tag tone={tone}>{tone === "case" ? "Case" : "Control"}</Tag>
        {fmtInt(proposed)} samples
      </div>
      <div className="mt-1 font-medium leading-snug">{label}</div>
      <div className="num mt-0.5 text-[13px] text-ink-2">
        {fitted == null
          ? "not fitted"
          : `${fmtInt(fitted)} fitted${dropped > 0 ? ` · ${dropped} unpaired, dropped` : ""}`}
      </div>
    </div>
  );
}

/** What was compared with what (left) and the notes the agent left while choosing it (right). */
export function ComparisonPanel({
  report,
  proposal,
}: {
  report: AnalysisReport;
  proposal: DesignProposal | null;
}) {
  const c = report.contrast;
  const de = report.de?.summary;
  const decisions = proposal?.decisions ?? [];
  const quals = proposal?.qualifications ?? [];
  const errors = proposal?.validation_errors ?? [];
  const hasNotes = decisions.length + quals.length + errors.length > 0 || Boolean(proposal?.notes);
  return (
    <Panel>
      <div className="grid gap-6 lg:grid-cols-2 lg:gap-x-8">
        <div className="grid content-start gap-4">
          <Arm
            tone="case"
            label={c.case_label}
            proposed={c.case_gsms.length}
            fitted={de?.n_case_used ?? null}
          />
          <Arm
            tone="control"
            label={c.control_label}
            proposed={c.control_gsms.length}
            fitted={de?.n_control_used ?? null}
          />
          {c.rationale && <p className="text-[13px] text-ink-2">{c.rationale}</p>}
          <a
            href={`https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${report.gse}`}
            target="_blank"
            rel="noreferrer"
            className="inline-flex items-center gap-1 self-start text-[13px] text-accent-ink no-underline hover:underline"
          >
            <span className="accession">{report.gse}</span> on GEO
            <ArrowUpRight size={12} />
          </a>
        </div>
        <div className="border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <ColHead label="How the contrast was decided" />
          {hasNotes ? (
            <div className="space-y-3 text-[13px] text-ink-2">
              {proposal?.notes && <p>{proposal.notes}</p>}
              {decisions.length > 0 && (
                <ul className="list-disc space-y-2 pl-4">
                  {decisions.map((d) => (
                    <li key={d}>{d}</li>
                  ))}
                </ul>
              )}
              {quals.length > 0 && (
                <div>
                  <div className="font-medium text-amber">Read the result with these caveats</div>
                  <ul className="mt-1 list-disc space-y-1 pl-4">
                    {quals.map((q) => (
                      <li key={q}>{q}</li>
                    ))}
                  </ul>
                </div>
              )}
              {errors.length > 0 && (
                <div>
                  <div className="font-medium">
                    {errors.length} label{errors.length === 1 ? "" : "s"} the GEO record could not
                    back, dropped
                  </div>
                  <ul className="mt-1 list-disc space-y-1 pl-4">
                    {errors.slice(0, 8).map((e) => (
                      <li key={e}>{e}</li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          ) : (
            <p className="text-[13px] text-ink-3">No notes were recorded for this contrast.</p>
          )}
        </div>
      </div>
    </Panel>
  );
}

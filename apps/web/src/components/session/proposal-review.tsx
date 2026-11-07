import { useState } from "react";
import type { DesignProposal, RunRequest } from "@/api/generated/types.gen";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Notice } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { Table, Td, Th } from "@/components/ui/table";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

/** The agent's proposed design, every reason to hesitate attached, and the confirm button. */
export function ProposalReview({
  proposal,
  genes,
  onGenesChange,
  onAnswer,
  onConfirm,
  busy,
  error,
}: {
  proposal: DesignProposal;
  genes: string[];
  onGenesChange: (genes: string[]) => void;
  onAnswer: (answers: string) => void;
  onConfirm: (design: RunRequest) => void;
  busy: boolean;
  error: string | null;
}) {
  const [answers, setAnswers] = useState("");
  const [gene, setGene] = useState("");
  const d = proposal.design;
  const validationErrors = proposal.validation_errors ?? [];
  const questions = proposal.questions ?? [];
  const problems = Object.entries(proposal.problems ?? {});
  const quals = Object.entries(proposal.qualifications ?? {});
  const blocked = problems.length > 0;
  const addGene = () => {
    const g = gene.trim().toUpperCase();
    if (g && !genes.includes(g)) onGenesChange([...genes, g]);
    setGene("");
  };
  const confirm = () => {
    onConfirm({
      ...d,
      genes,
      contrasts: d.contrasts.map((c) => ({ ...c, status: "confirmed" })),
    });
  };
  const samplesByGsm = new Map(d.samplesheet.samples.map((s) => [s.gsm, s]));
  return (
    <div className="space-y-4">
      {proposal.notes && <p className="text-sm text-ink-2">{proposal.notes}</p>}
      {validationErrors.length > 0 && (
        <Notice
          tone="amber"
          title={`${validationErrors.length} label${validationErrors.length === 1 ? "" : "s"} could not be backed by the GEO record and were dropped`}
        >
          <ul>
            {validationErrors.slice(0, 8).map((e) => (
              <li key={e}>{e}</li>
            ))}
          </ul>
        </Notice>
      )}
      {problems.length > 0 && (
        <Notice tone="danger" title="This design cannot run as proposed">
          <ul>
            {problems.flatMap(([name, ps]) => ps.map((p) => <li key={`${name}-${p}`}>{p}</li>))}
          </ul>
        </Notice>
      )}
      {quals.length > 0 && (
        <Notice tone="amber" title="If you run it, the result will carry these caveats">
          <ul>{quals.flatMap(([name, qs]) => qs.map((q) => <li key={`${name}-${q}`}>{q}</li>))}</ul>
        </Notice>
      )}
      {questions.length > 0 && (
        <Card className="p-4">
          <h3>The specialist needs a decision from you</h3>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
            {questions.map((q) => (
              <li key={q}>{q}</li>
            ))}
          </ul>
          <Label htmlFor="answers" className="mt-3">
            Your answer
          </Label>
          <Textarea
            id="answers"
            rows={2}
            value={answers}
            onChange={(e) => setAnswers(e.target.value)}
            className="mt-1"
            placeholder="e.g. use healthy donors as the control, ignore treated samples"
          />
          <Button
            className="mt-2"
            onClick={() => onAnswer(answers)}
            disabled={busy || !answers.trim()}
          >
            Redesign with this answer
          </Button>
        </Card>
      )}

      {d.contrasts.map((c) => (
        <Card key={c.name} className="p-4">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3>
              <span className="font-mono text-[15px]">{c.name}</span>
            </h3>
            <span className="text-[13px] text-ink-2">
              confidence {c.confidence != null ? fmtNum(c.confidence, 2) : "n/a"} ·{" "}
              <Badge tone={c.status === "proposed" ? "neutral" : "ok"}>{c.status}</Badge>
            </span>
          </div>
          <div className="mt-3 grid gap-3 sm:grid-cols-2">
            <div className="border-l-[3px] border-case pl-3">
              <div className="text-[13px] text-ink-2">Case · {c.case_gsms.length} samples</div>
              <div className="font-medium">{c.case_label}</div>
            </div>
            <div className="border-l-[3px] border-control pl-3">
              <div className="text-[13px] text-ink-2">
                Control · {c.control_gsms.length} samples
              </div>
              <div className="font-medium">{c.control_label}</div>
            </div>
          </div>
          {(c.blocking || c.rationale) && (
            <p className="mt-3 text-sm text-ink-2">
              {c.blocking && (
                <>
                  Paired by <span className="font-medium text-ink">{c.blocking}</span>.{" "}
                </>
              )}
              {c.rationale}
            </p>
          )}
          <div className="mt-3">
            <Table>
              <thead>
                <tr>
                  <Th>Sample</Th>
                  <Th>Arm</Th>
                  <Th>Labels</Th>
                  <Th>Evidence</Th>
                  <Th className="text-right">Conf.</Th>
                </tr>
              </thead>
              <tbody>
                {[
                  ...c.case_gsms.map((g) => [g, "case"] as const),
                  ...c.control_gsms.map((g) => [g, "control"] as const),
                ].map(([gsm, arm]) => {
                  const s = samplesByGsm.get(gsm);
                  const low = s?.confidence != null && s.confidence < 0.7;
                  return (
                    <tr key={gsm} className={cn(low && "bg-amber-soft/40")}>
                      <Td className="accession whitespace-nowrap">
                        {gsm}
                        {s?.title && (
                          <div className="font-sans text-[12px] text-ink-3">{s.title}</div>
                        )}
                      </Td>
                      <Td>
                        <Badge tone={arm === "case" ? "case" : "control"}>{arm}</Badge>
                      </Td>
                      <Td className="text-[13px]">
                        {s ? (
                          [
                            s.condition,
                            s.tissue,
                            s.treatment,
                            s.donor && `donor ${s.donor}`,
                            s.time_point,
                          ]
                            .filter(Boolean)
                            .join(" · ") || <span className="text-ink-3">—</span>
                        ) : (
                          <span className="text-danger">not in sheet</span>
                        )}
                      </Td>
                      <Td className="text-[13px]">
                        <div className="flex flex-wrap gap-1">
                          {(s?.evidence ?? []).map((e) => (
                            <span
                              key={e}
                              className="rounded-sm bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-ink-2"
                            >
                              “{e}”
                            </span>
                          ))}
                        </div>
                      </Td>
                      <Td className={cn("num text-right", low && "text-amber")}>
                        {s?.confidence != null ? fmtNum(s.confidence, 2) : "—"}
                      </Td>
                    </tr>
                  );
                })}
              </tbody>
            </Table>
          </div>
        </Card>
      ))}

      <Card className="p-4">
        <h3>Genes to answer for</h3>
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {genes.map((g) => (
            <Chip key={g} tone="case" onRemove={() => onGenesChange(genes.filter((x) => x !== g))}>
              {g}
            </Chip>
          ))}
          <Input
            value={gene}
            onChange={(e) => setGene(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                addGene();
              }
            }}
            onBlur={addGene}
            placeholder="add a symbol"
            className="h-8 w-36 text-[13px]"
            aria-label="Add a gene symbol"
          />
        </div>
      </Card>

      {error && (
        <Notice tone="danger" title="The run could not start">
          {error}
        </Notice>
      )}
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="primary" size="lg" onClick={confirm} disabled={busy || blocked}>
          {busy ? "Starting…" : "Confirm the design and run"}
        </Button>
        <span className="text-[13px] text-ink-2">
          {blocked
            ? "Fix the problems above (ask the specialist to redesign) before running."
            : "Confirming records that you checked the labels and arms."}
        </span>
      </div>
    </div>
  );
}

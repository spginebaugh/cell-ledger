import { Link } from "@tanstack/react-router";
import { ArrowRight, Loader2 } from "lucide-react";
import { useState } from "react";
import type { CompareRequest, ComparisonStatus, RunStatus } from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Empty, ErrorBox } from "@/components/ui/card";
import { Dialog } from "@/components/ui/dialog";
import { Input, Label } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { statusLabel, statusTone } from "@/lib/format";
import { useStartComparison } from "@/lib/queries";
import { slugify } from "@/lib/ui-state";

export function ComparisonsSection({
  sessionId,
  comparisons,
  runs,
  question,
  genes,
}: {
  sessionId: string;
  comparisons: ComparisonStatus[];
  runs: RunStatus[];
  question: string;
  genes: string[];
}) {
  const [open, setOpen] = useState(false);
  const finished = runs.filter((r) => r.status !== "running");
  return (
    <>
      <div className="space-y-3">
        {comparisons.length === 0 ? (
          <Empty title="No comparisons yet">
            {finished.length >= 2
              ? "Pool two or more finished runs to see which genes replicate across datasets."
              : "A comparison needs at least two finished runs."}
          </Empty>
        ) : (
          comparisons.map((c) => (
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
                  {c.request.question} · {c.request.members.length} datasets
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
          ))
        )}
        {finished.length >= 2 && (
          <Button variant="primary" onClick={() => setOpen(true)}>
            Compare runs
          </Button>
        )}
      </div>
      <CompareDialog
        open={open}
        onOpenChange={setOpen}
        sessionId={sessionId}
        runs={finished}
        question={question}
        genes={genes}
      />
    </>
  );
}

function CompareDialog({
  open,
  onOpenChange,
  sessionId,
  runs,
  question,
  genes,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  sessionId: string;
  runs: RunStatus[];
  question: string;
  genes: string[];
}) {
  const first = runs[0]?.report?.contrast;
  const [name, setName] = useState(slugify(question).slice(0, 40) || "comparison");
  const [q, setQ] = useState(question);
  const [caseLabel, setCaseLabel] = useState(first?.case_label ?? "case");
  const [controlLabel, setControlLabel] = useState(first?.control_label ?? "control");
  const [geneText, setGeneText] = useState(genes.join(", "));
  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(runs.filter((r) => r.status === "complete").map((r) => `${r.gse}/${r.contrast}`)),
  );
  const start = useStartComparison(sessionId);
  const toggle = (k: string) =>
    setSelected((s) => {
      const n = new Set(s);
      if (n.has(k)) n.delete(k);
      else n.add(k);
      return n;
    });
  const submit = async () => {
    const members = runs
      .filter((r) => selected.has(`${r.gse}/${r.contrast}`))
      .map((r) => ({ gse: r.gse, contrast: r.contrast }));
    const body: CompareRequest = {
      name: slugify(name),
      question: q,
      case_label: caseLabel,
      control_label: controlLabel,
      members,
      genes_of_interest: geneText
        .split(/[,\s]+/)
        .map((g) => g.trim().toUpperCase())
        .filter(Boolean),
      min_studies: Math.min(3, members.length),
    };
    await start.mutateAsync(body);
    onOpenChange(false);
  };
  return (
    <Dialog
      open={open}
      onOpenChange={onOpenChange}
      title="Compare runs"
      description="Each dataset keeps its own DESeq2 fit; the comparison pools per-gene effects and reports what replicates."
    >
      <div className="space-y-4">
        <fieldset>
          <legend className="text-[13px] font-medium text-ink-2">
            Runs to pool (at least two)
          </legend>
          <div className="mt-2 space-y-1.5">
            {runs.map((r) => {
              const k = `${r.gse}/${r.contrast}`;
              return (
                <label key={k} className="flex items-start gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={selected.has(k)}
                    onChange={() => toggle(k)}
                    className="mt-1"
                  />
                  <span>
                    <span className="accession">{r.gse}</span>{" "}
                    <span className="font-mono text-[13px] text-ink-2">{r.contrast}</span>
                    {r.status !== "complete" && (
                      <Badge tone={statusTone(r.status)} className="ml-2">
                        {statusLabel(r.status)}
                      </Badge>
                    )}
                    {r.report && (
                      <span className="block text-[12px] text-ink-3">
                        {r.report.contrast.case_label} vs {r.report.contrast.control_label}
                      </span>
                    )}
                  </span>
                </label>
              );
            })}
          </div>
        </fieldset>
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <Label htmlFor="cmp-name">Name</Label>
            <Input
              id="cmp-name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              className="mt-1 font-mono text-[13px]"
            />
          </div>
          <div>
            <Label htmlFor="cmp-genes">Genes to answer for</Label>
            <Input
              id="cmp-genes"
              value={geneText}
              onChange={(e) => setGeneText(e.target.value)}
              className="mt-1"
            />
          </div>
          <div className="sm:col-span-2">
            <Label htmlFor="cmp-q">Question</Label>
            <Input id="cmp-q" value={q} onChange={(e) => setQ(e.target.value)} className="mt-1" />
          </div>
          <div>
            <Label htmlFor="cmp-case">Case label</Label>
            <Input
              id="cmp-case"
              value={caseLabel}
              onChange={(e) => setCaseLabel(e.target.value)}
              className="mt-1"
            />
          </div>
          <div>
            <Label htmlFor="cmp-control">Control label</Label>
            <Input
              id="cmp-control"
              value={controlLabel}
              onChange={(e) => setControlLabel(e.target.value)}
              className="mt-1"
            />
          </div>
        </div>
        {start.isError && (
          <ErrorBox title="Could not start the comparison">{errorMessage(start.error)}</ErrorBox>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            Cancel
          </Button>
          <Button
            variant="primary"
            onClick={() => void submit()}
            disabled={selected.size < 2 || start.isPending || !q.trim()}
          >
            {start.isPending ? "Starting…" : `Compare ${selected.size} runs`}
          </Button>
        </div>
      </div>
    </Dialog>
  );
}

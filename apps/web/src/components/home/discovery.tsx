import { useState } from "react";
import type { Candidate, DiscoveryResult } from "@/api/generated/types.gen";
import { AgentFeed } from "@/components/session/agent-feed";
import { Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, Details, ErrorBox, Notice } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import type { FeedItem } from "@/lib/useSse";
import { cn } from "@/lib/utils";

export function DiscoveryView({
  result,
  feed,
  streaming,
  error,
  genes,
  onGenesChange,
  selected,
  onToggle,
  onAnswer,
  onCollect,
  collecting,
}: {
  result: DiscoveryResult | null;
  feed: FeedItem[];
  streaming: boolean;
  error: string | null;
  genes: string[];
  onGenesChange: (g: string[]) => void;
  selected: Set<string>;
  onToggle: (gse: string) => void;
  onAnswer: (answers: string) => void;
  onCollect: () => void;
  collecting: boolean;
}) {
  const [answers, setAnswers] = useState("");
  const [gene, setGene] = useState("");
  const addGene = () => {
    const g = gene.trim().toUpperCase();
    if (g && !genes.includes(g)) onGenesChange([...genes, g]);
    setGene("");
  };
  return (
    <div className="space-y-5">
      {(streaming || (!result && feed.length > 0)) && (
        <AgentFeed
          feed={feed}
          streaming={streaming}
          label={streaming ? "Searching GEO" : "What the specialist did"}
        />
      )}
      {error && <ErrorBox title="The search failed">{error}</ErrorBox>}
      {result && (
        <>
          <Card className="p-5">
            <div className="text-[13px] text-ink-2">Read as</div>
            <p className="mt-1 font-display text-[1.25rem] leading-snug">{result.interpretation}</p>
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-[13px] text-ink-2">Genes to answer for</span>
              {genes.map((g) => (
                <Chip
                  key={g}
                  tone="case"
                  onRemove={() => onGenesChange(genes.filter((x) => x !== g))}
                >
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
            {(result.queries_tried ?? []).length > 0 && (
              <p className="mt-3 text-[12px] text-ink-3">
                Searched GEO for: {(result.queries_tried ?? []).join(" · ")}
              </p>
            )}
          </Card>

          {(result.clarifying_questions ?? []).length > 0 && (
            <Card className="border-amber/40 p-5">
              <h3>Before choosing datasets, the specialist asks</h3>
              <ul className="mt-2 list-disc space-y-1 pl-5 text-sm">
                {(result.clarifying_questions ?? []).map((q) => (
                  <li key={q}>{q}</li>
                ))}
              </ul>
              <Label htmlFor="disc-answers" className="mt-3">
                Your answer
              </Label>
              <Textarea
                id="disc-answers"
                rows={2}
                value={answers}
                onChange={(e) => setAnswers(e.target.value)}
                className="mt-1"
              />
              <div className="mt-2 flex flex-wrap items-center gap-3">
                <Button onClick={() => onAnswer(answers)} disabled={streaming || !answers.trim()}>
                  Search again with this answer
                </Button>
                <span className="text-[13px] text-ink-2">
                  or pick from the candidates below that fit every reading.
                </span>
              </div>
            </Card>
          )}

          {(result.candidates ?? []).length === 0 ? (
            <Notice tone="amber" title="No usable dataset came back from GEO">
              The search tried {(result.queries_tried ?? []).length} wordings. Broaden the question
              (organism, synonyms, drop a control requirement) and search again.
            </Notice>
          ) : (
            <div>
              <h3>
                {(result.candidates ?? []).length} candidate dataset
                {(result.candidates ?? []).length === 1 ? "" : "s"}
              </h3>
              <p className="mt-0.5 text-[13px] text-ink-2">
                Every accession here was confirmed by GEO in this search. Tick the ones to download.
              </p>
              <div className="mt-3 grid gap-3 md:grid-cols-2">
                {(result.candidates ?? []).map((c) => (
                  <CandidateCard
                    key={c.gse}
                    c={c}
                    checked={selected.has(c.gse)}
                    onToggle={() => onToggle(c.gse)}
                  />
                ))}
              </div>
            </div>
          )}

          {(result.rejected ?? []).length > 0 && (
            <Details summary={`${(result.rejected ?? []).length} series looked at and set aside`}>
              <ul className="space-y-1 text-sm">
                {(result.rejected ?? []).map((r) => (
                  <li key={r.gse}>
                    <span className="accession">{r.gse}</span>{" "}
                    <span className="text-ink-2">— {r.why}</span>
                  </li>
                ))}
              </ul>
            </Details>
          )}

          <div className="flex flex-wrap items-center gap-3">
            <Button
              variant="primary"
              size="lg"
              onClick={onCollect}
              disabled={selected.size === 0 || collecting}
            >
              {collecting
                ? "Starting downloads…"
                : `Download ${selected.size || ""} dataset${selected.size === 1 ? "" : "s"} and continue`}
            </Button>
            <span className="text-[13px] text-ink-2">
              Counts and sample records come from NCBI; nothing is inferred from the paper.
            </span>
          </div>
        </>
      )}
    </div>
  );
}

function CandidateCard({
  c,
  checked,
  onToggle,
}: {
  c: Candidate;
  checked: boolean;
  onToggle: () => void;
}) {
  return (
    <label
      className={cn(
        "flex cursor-pointer gap-3 rounded-lg border bg-surface p-4 transition-colors",
        checked ? "border-ink" : "border-line hover:border-line-2",
      )}
      style={{ boxShadow: "var(--shadow)" }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-1 h-4 w-4 shrink-0"
      />
      <span className="min-w-0">
        <span className="flex flex-wrap items-baseline gap-2">
          <span className="accession font-medium">{c.gse}</span>
          <span className="num text-[12px] text-ink-3">{c.n_samples} samples</span>
        </span>
        <span className="mt-0.5 block font-medium leading-snug">{c.title}</span>
        <span className="mt-1.5 block text-[13px] text-ink-2">{c.why}</span>
        <span className="mt-2 grid gap-1 text-[13px]">
          <span className="border-l-[3px] border-case pl-2">
            <span className="text-ink-3">case: </span>
            {c.case_hint}
          </span>
          <span className="border-l-[3px] border-control pl-2">
            <span className="text-ink-3">control: </span>
            {c.control_hint}
          </span>
        </span>
        {(c.concerns ?? []).length > 0 && (
          <span className="mt-2 block text-[12px] text-amber">
            {(c.concerns ?? []).join(" · ")}
          </span>
        )}
      </span>
    </label>
  );
}

import { useState } from "react";
import type { Candidate, DiscoveryResult } from "@/api/generated/types.gen";
import { AgentFeed } from "@/components/session/agent-feed";
import { Chip, Tag } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ColHead, Details, ErrorBox, Notice, Panel, Pill } from "@/components/ui/card";
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
  const candidates = result?.candidates ?? [];
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
          <Panel className="p-5">
            <Pill label="Read as">{result.interpretation}</Pill>
            <div className="mt-4 flex flex-wrap items-center gap-1.5">
              <span className="mr-1 text-[12px] text-ink-2">Genes to answer for</span>
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
                className="h-7 w-36 font-mono text-[12px]"
                aria-label="Add a gene symbol"
              />
            </div>
            {(result.queries_tried ?? []).length > 0 && (
              <p className="mt-3 text-[12px] text-ink-3">
                Searched GEO for: {(result.queries_tried ?? []).join(" · ")}
              </p>
            )}
          </Panel>

          {result.out_of_scope && (
            <Notice tone="amber" title="Out of Scope: Not a Question cell ledger Can Answer">
              {result.out_of_scope} It only works with human bulk RNA-seq series in GEO that have
              NCBI raw counts.
            </Notice>
          )}

          {(result.clarifying_questions ?? []).length > 0 && (
            <Panel className="border-l-[3px] border-l-amber p-5">
              <h3 className="text-amber">Before choosing datasets, the specialist asks</h3>
              <ul className="mt-2 space-y-3 text-[13px]">
                {(result.clarifying_questions ?? []).map((q) => (
                  <li key={q.question}>
                    <p className="font-medium">{q.question}</p>
                    <p className="mt-0.5 text-[13px] text-ink-2">{q.why}</p>
                    {(q.options ?? []).length > 0 && (
                      <div className="mt-1.5 flex flex-wrap gap-1.5">
                        {(q.options ?? []).map((o) => (
                          <button
                            key={o}
                            type="button"
                            onClick={() => setAnswers((a) => (a ? `${a}\n${o}` : o))}
                            className="h-7 rounded-md border border-line-2 bg-surface-2 px-2.5 text-[12px] text-ink-2 hover:border-accent hover:text-ink"
                          >
                            {o}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
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
            </Panel>
          )}

          {candidates.length === 0 && !result.out_of_scope ? (
            <Notice tone="amber" title="No usable dataset came back from GEO">
              The search tried {(result.queries_tried ?? []).length} wordings. Broaden the question
              (organism, synonyms, drop a control requirement) and search again.
            </Notice>
          ) : (
            <Panel>
              <ColHead
                label={`${candidates.length} candidate dataset${candidates.length === 1 ? "" : "s"}`}
                detail="Every accession here was confirmed by GEO in this search. Tick the ones to download."
              />
              <div className="grid gap-3 md:grid-cols-2">
                {candidates.map((c) => (
                  <CandidateCard
                    key={c.gse}
                    c={c}
                    checked={selected.has(c.gse)}
                    onToggle={() => onToggle(c.gse)}
                  />
                ))}
              </div>
              {(result.rejected ?? []).length > 0 && (
                <div className="mt-4 border-t border-line pt-3">
                  <Details
                    summary={`${(result.rejected ?? []).length} series looked at and set aside`}
                  >
                    <ul className="space-y-1">
                      {(result.rejected ?? []).map((r) => (
                        <li key={r.gse}>
                          <span className="accession font-medium text-accent-ink">{r.gse}</span>{" "}
                          <span className="text-ink-2">— {r.why}</span>
                        </li>
                      ))}
                    </ul>
                  </Details>
                </div>
              )}
            </Panel>
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
        checked ? "border-accent" : "border-line hover:border-line-2",
      )}
      style={{ boxShadow: "var(--shadow)" }}
    >
      <input
        type="checkbox"
        checked={checked}
        onChange={onToggle}
        className="mt-1 h-4 w-4 shrink-0 accent-[var(--accent)]"
      />
      <span className="min-w-0">
        <span className="flex flex-wrap items-center gap-2">
          <span className="accession font-bold text-accent-ink">{c.gse}</span>
          <span className="num text-[12px] text-ink-3">{c.n_samples} samples</span>
        </span>
        <span className="mt-0.5 block font-medium leading-snug">{c.title}</span>
        <span className="mt-1.5 block text-[13px] text-ink-2">{c.why}</span>
        <span className="mt-3 grid gap-2 text-[13px]">
          <span className="border-l-[3px] border-case pl-2">
            <Tag tone="case" className="mr-2">
              Case
            </Tag>
            {c.case_hint}
          </span>
          <span className="border-l-[3px] border-control pl-2">
            <Tag tone="control" className="mr-2">
              Control
            </Tag>
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

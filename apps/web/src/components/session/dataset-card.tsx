import { Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { DatasetStatus, DesignProposal, RunRequest } from "@/api/generated/types.gen";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox, Notice } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { humanExclusion, statusLabel, statusTone } from "@/lib/format";
import { useSse } from "@/lib/useSse";
import { AgentFeed } from "./agent-feed";
import { ProposalReview } from "./proposal-review";

export function DatasetCard({
  sessionId,
  dataset,
  question,
  agentAvailable,
  defaultGenes,
  proposal,
  onProposal,
  onStartRun,
  starting,
  startError,
  hasRun,
}: {
  sessionId: string;
  dataset: DatasetStatus;
  question: string;
  agentAvailable: boolean;
  defaultGenes: string[];
  proposal: DesignProposal | undefined;
  onProposal: (gse: string, p: DesignProposal | null) => void;
  onStartRun: (design: RunRequest) => Promise<void>;
  starting: boolean;
  startError: string | null;
  hasRun: boolean;
}) {
  const [mode, setMode] = useState<"idle" | "design" | "upload">(proposal ? "design" : "idle");
  const [genes, setGenes] = useState<string[]>(defaultGenes);
  const sse = useSse<DesignProposal>();
  const r = dataset.record;
  const total = r?.samples?.length ?? 0;

  useEffect(() => {
    if (sse.result) onProposal(dataset.gse, sse.result);
  }, [sse.result, dataset.gse, onProposal]);

  const design = (answers?: string) => {
    setMode("design");
    onProposal(dataset.gse, null);
    void sse.start(`/api/sessions/${sessionId}/datasets/${dataset.gse}/design`, {
      question,
      answers: answers || null,
      genes,
    });
  };

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
            {hasRun && <Badge tone="neutral">has a run</Badge>}
          </div>
          {r?.title && <h3 className="mt-1.5 leading-snug">{r.title}</h3>}
          {r && dataset.status === "ready" && (
            <p className="num mt-1 text-[13px] text-ink-2">
              {r.n_eligible} of {total} samples are human bulk RNA-seq with counts
              {r.counts_check ? ` · ${r.counts_check.n_genes.toLocaleString()} genes` : ""}
              {(r.pubmed_ids ?? []).length > 0 && (
                <>
                  {" · "}
                  <a
                    className="underline-offset-2 hover:underline"
                    href={`https://pubmed.ncbi.nlm.nih.gov/${r.pubmed_ids?.[0]}/`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    PubMed {r.pubmed_ids?.[0]}
                  </a>
                </>
              )}
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
        {dataset.status === "ready" && (
          <div className="flex shrink-0 flex-wrap gap-2">
            {agentAvailable && (
              <Button
                variant="primary"
                onClick={() => design()}
                disabled={sse.status === "streaming"}
              >
                Design the contrast
              </Button>
            )}
            <Button onClick={() => setMode(mode === "upload" ? "idle" : "upload")}>
              Upload a design
            </Button>
          </div>
        )}
      </div>

      {mode === "design" && (
        <div className="mt-5 space-y-4">
          {(sse.status === "streaming" || (sse.feed.length > 0 && !proposal)) && (
            <AgentFeed
              feed={sse.feed}
              streaming={sse.status === "streaming"}
              label={
                sse.status === "streaming"
                  ? "Reading the GEO record and labelling samples"
                  : "What the specialist did"
              }
            />
          )}
          {sse.status === "error" && sse.error && (
            <ErrorBox title="The design step failed">{sse.error}</ErrorBox>
          )}
          {proposal && (
            <ProposalReview
              proposal={proposal}
              genes={genes}
              onGenesChange={setGenes}
              onAnswer={(answers) => design(answers)}
              onConfirm={(d) => void onStartRun(d)}
              busy={starting}
              error={startError}
            />
          )}
        </div>
      )}

      {mode === "upload" && (
        <div className="mt-5">
          <UploadDesign
            gse={dataset.gse}
            defaultGenes={genes}
            onSubmit={(d) => void onStartRun(d)}
            busy={starting}
            error={startError}
          />
        </div>
      )}
    </Card>
  );
}

/** Manual path: paste a design file ({samplesheet, contrasts, markers}) and start a run. */
export function UploadDesign({
  gse,
  defaultGenes,
  onSubmit,
  busy,
  error,
}: {
  gse: string;
  defaultGenes: string[];
  onSubmit: (d: RunRequest) => void;
  busy: boolean;
  error: string | null;
}) {
  const [text, setText] = useState("");
  const [genes, setGenes] = useState(defaultGenes.join(", "));
  const [parseError, setParseError] = useState<string | null>(null);
  const submit = () => {
    try {
      const doc = JSON.parse(text);
      if (!doc.samplesheet || !Array.isArray(doc.contrasts))
        throw new Error("expected an object with samplesheet and contrasts");
      if (doc.samplesheet.gse !== gse)
        throw new Error(`the design is for ${doc.samplesheet.gse}, not ${gse}`);
      const req: RunRequest = {
        samplesheet: doc.samplesheet,
        contrasts: doc.contrasts.map((c: RunRequest["contrasts"][number]) => ({
          ...c,
          status: c.status === "proposed" ? "confirmed" : c.status,
        })),
        markers: doc.markers ?? [],
        genes: genes
          .split(/[,\s]+/)
          .map((g) => g.trim().toUpperCase())
          .filter(Boolean),
        enrichment: true,
        figures: true,
      };
      setParseError(null);
      onSubmit(req);
    } catch (e) {
      setParseError(errorMessage(e));
    }
  };
  const onFile = async (f: File | undefined) => {
    if (f) setText(await f.text());
  };
  return (
    <div className="space-y-3">
      <Notice tone="neutral" title="A design is a sample sheet plus one or more contrasts">
        Paste the JSON (the same format as{" "}
        <code className="font-mono text-[12px]">
          packages/core/tests/fixtures/geo_examples/{gse}.json
        </code>
        ) or pick a file. Proposed contrasts are treated as confirmed by you.
      </Notice>
      <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
        <Textarea
          rows={6}
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder='{"samplesheet": {...}, "contrasts": [...], "markers": [...]}'
          className="font-mono text-[12px]"
          aria-label="Design JSON"
        />
        <div className="space-y-2">
          <Label htmlFor={`file-${gse}`}>or a file</Label>
          <input
            id={`file-${gse}`}
            type="file"
            accept="application/json,.json"
            onChange={(e) => void onFile(e.target.files?.[0])}
            className="block text-[13px]"
          />
        </div>
      </div>
      <div>
        <Label htmlFor={`genes-${gse}`}>Genes to answer for</Label>
        <Input
          id={`genes-${gse}`}
          value={genes}
          onChange={(e) => setGenes(e.target.value)}
          placeholder="IL17A, IL23A"
          className="mt-1 max-w-md"
        />
      </div>
      {genes.split(/[,\s]+/).filter(Boolean).length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {genes
            .split(/[,\s]+/)
            .filter(Boolean)
            .map((g) => (
              <Chip key={g} tone="case">
                {g.toUpperCase()}
              </Chip>
            ))}
        </div>
      )}
      {(parseError || error) && (
        <ErrorBox title="Could not start the run">{parseError ?? error}</ErrorBox>
      )}
      <Button variant="primary" onClick={submit} disabled={busy || !text.trim()}>
        {busy ? "Starting…" : "Run the pipeline"}
      </Button>
    </div>
  );
}

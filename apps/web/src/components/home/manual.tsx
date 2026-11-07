import { useState } from "react";
import type { GeoSeriesHit } from "@/api/generated/types.gen";
import { Badge, Chip } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, ErrorBox } from "@/components/ui/card";
import { Input, Label, Textarea } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import { useVerifyGeo } from "@/lib/queries";

/** The path that always works: paste accessions, check them against GEO, download. */
export function ManualAccessions({
  genes,
  onGenesChange,
  onCollect,
  collecting,
  intro,
}: {
  genes: string[];
  onGenesChange: (g: string[]) => void;
  onCollect: (gses: string[]) => void;
  collecting: boolean;
  intro?: string;
}) {
  const [text, setText] = useState("");
  const [gene, setGene] = useState("");
  const verify = useVerifyGeo();
  const accessions = [...new Set(text.toUpperCase().match(/GSE\d+/g) ?? [])];
  const hits: GeoSeriesHit[] = verify.data?.hits ?? [];
  const ineligible = verify.data?.ineligible ?? [];
  const addGene = () => {
    const g = gene.trim().toUpperCase();
    if (g && !genes.includes(g)) onGenesChange([...genes, g]);
    setGene("");
  };
  return (
    <Card className="p-5">
      <h3>Start from accessions you already know</h3>
      <p className="mt-1 text-sm text-ink-2">
        {intro ??
          "Paste GEO series accessions. Each is checked against GEO: only human bulk RNA-seq with NCBI raw counts can be analysed."}
      </p>
      <Label htmlFor="accessions" className="mt-4">
        Accessions
      </Label>
      <Textarea
        id="accessions"
        rows={2}
        value={text}
        onChange={(e) => setText(e.target.value)}
        placeholder="GSE47944, GSE54456"
        className="mt-1 font-mono text-[13px]"
      />
      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className="mr-1 text-[13px] text-ink-2">Genes to answer for</span>
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
      <div className="mt-4 flex flex-wrap items-center gap-2">
        <Button
          onClick={() => verify.mutate(accessions)}
          disabled={accessions.length === 0 || verify.isPending}
        >
          {verify.isPending
            ? "Checking with GEO…"
            : `Check ${accessions.length || ""} accession${accessions.length === 1 ? "" : "s"}`}
        </Button>
        <Button
          variant="primary"
          onClick={() => onCollect(hits.length ? hits.map((h) => h.gse) : accessions)}
          disabled={accessions.length === 0 || collecting}
        >
          {collecting
            ? "Starting downloads…"
            : hits.length
              ? `Download ${hits.length} eligible`
              : "Download without checking"}
        </Button>
      </div>
      {verify.isError && (
        <div className="mt-3">
          <ErrorBox title="GEO could not be reached">{errorMessage(verify.error)}</ErrorBox>
        </div>
      )}
      {verify.data && (
        <ul className="mt-4 space-y-2 text-sm">
          {hits.map((h) => (
            <li key={h.gse} className="flex flex-wrap items-baseline gap-2">
              <Badge tone="ok">eligible</Badge>
              <span className="accession font-medium">{h.gse}</span>
              <span className="text-ink-2">{h.title}</span>
              <span className="num text-[12px] text-ink-3">{h.n_samples} samples</span>
            </li>
          ))}
          {ineligible.map((g) => (
            <li key={g} className="flex flex-wrap items-baseline gap-2">
              <Badge tone="danger">not usable</Badge>
              <span className="accession">{g}</span>
              <span className="text-ink-2">
                not in GEO, not human bulk RNA-seq, or no NCBI counts
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

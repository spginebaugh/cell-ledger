import type { GeneLookupAcross, GeneMeta } from "@/api/generated/types.gen";
import { Forest } from "@/components/charts/forest";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import { fmtLfc, fmtNum, fmtP, verdictGlyph, verdictLabel, verdictTone } from "@/lib/format";
import { cn } from "@/lib/utils";

export function GeneAcrossCard({
  lookup,
  members,
}: {
  lookup: GeneLookupAcross;
  members: string[];
}) {
  const tone = verdictTone(lookup.verdict);
  const m = lookup.meta;
  return (
    <Card className="p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-display text-[1.35rem] leading-none">
            {lookup.symbol ?? lookup.query}
          </div>
          <Badge tone={tone} className="mt-2">
            {verdictLabel(lookup.verdict)}
          </Badge>
        </div>
        <span
          aria-hidden
          className={cn(
            "font-display text-[1.6rem] leading-none",
            tone === "case" && "text-case",
            tone === "control" && "text-control",
            tone === "amber" && "text-amber",
            tone === "muted" && "text-ink-3",
          )}
        >
          {verdictGlyph(lookup.verdict)}
        </span>
      </div>
      <p className="mt-2 text-[13px] text-ink-2">{lookup.detail}</p>
      {m?.pooled_log2fc != null && (
        <dl className="num mt-3 grid grid-cols-2 gap-x-3 gap-y-1 text-[13px]">
          <dt className="text-ink-2">pooled log2FC</dt>
          <dd className="text-right font-medium">{fmtLfc(m.pooled_log2fc)}</dd>
          <dt className="text-ink-2">95% interval</dt>
          <dd className="text-right">
            {fmtLfc(m.ci_low)} to {fmtLfc(m.ci_high)}
          </dd>
          <dt className="text-ink-2">pooled padj</dt>
          <dd className="text-right">{fmtP(m.padj)}</dd>
          <dt className="text-ink-2">tested in</dt>
          <dd className="text-right">
            {m.n_tested} datasets
            {m.i2 != null && <span className="text-ink-3"> · I² {fmtNum(m.i2)}</span>}
          </dd>
        </dl>
      )}
      {lookup.gene_id && (
        <div className="mt-3">
          <Forest lookup={lookup} members={members} />
        </div>
      )}
      {(lookup.driven_by ?? []).length > 0 && (
        <p className="mt-2 text-[12px] text-amber">
          The verdict changes without{" "}
          {(lookup.driven_by ?? []).map((d) => d.split(":")[0]).join(", ")}.
        </p>
      )}
    </Card>
  );
}

export function RobustGenes({ title, rows }: { title: string; rows: GeneMeta[] }) {
  return (
    <div>
      <h3>{title}</h3>
      <div className="mt-2">
        <Table>
          <thead>
            <tr>
              <Th>Gene</Th>
              <Th className="text-right">pooled log2FC</Th>
              <Th className="text-right">95% CI</Th>
              <Th className="text-right">padj</Th>
              <Th className="text-right">tested</Th>
              <Th className="text-right">replication</Th>
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, 15).map((g) => (
              <tr key={g.gene_id}>
                <Td className="font-medium">
                  {g.symbol ?? <span className="accession">{g.gene_id}</span>}
                </Td>
                <Td
                  className={cn(
                    "num text-right",
                    (g.pooled_log2fc ?? 0) > 0 ? "text-case" : "text-control",
                  )}
                >
                  {fmtLfc(g.pooled_log2fc)}
                </Td>
                <Td className="num text-right text-ink-2">
                  {fmtLfc(g.ci_low)} to {fmtLfc(g.ci_high)}
                </Td>
                <Td className="num text-right">{fmtP(g.padj)}</Td>
                <Td className="num text-right">{g.n_tested}</Td>
                <Td className="num text-right">{Math.round(g.replication * 100)}%</Td>
              </tr>
            ))}
          </tbody>
        </Table>
      </div>
    </div>
  );
}

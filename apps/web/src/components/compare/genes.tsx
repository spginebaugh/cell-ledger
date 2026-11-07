import type { GeneLookupAcross, GeneMeta } from "@/api/generated/types.gen";
import { Forest } from "@/components/charts/forest";
import { Badge, Tag } from "@/components/ui/badge";
import { ColHead, Details, KeyValues, Panel } from "@/components/ui/card";
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
    <Panel className="px-4 py-3">
      <div className="flex min-h-[30px] items-center justify-between gap-3">
        <span
          className="font-display text-[26px] font-medium leading-none"
          style={{ fontVariationSettings: '"opsz" 48' }}
        >
          {lookup.symbol ?? lookup.query}
        </span>
        <span className="inline-flex items-center gap-3">
          <Badge tone={tone}>{verdictLabel(lookup.verdict)}</Badge>
          <span
            aria-hidden
            className={cn(
              "text-[20px] leading-none",
              tone === "case" && "text-case",
              tone === "control" && "text-control",
              tone === "amber" && "text-amber",
              tone === "muted" && "text-ink-3",
            )}
          >
            {verdictGlyph(lookup.verdict)}
          </span>
        </span>
      </div>
      {lookup.gene_id && (
        <div className="mt-3">
          <Forest lookup={lookup} members={members} />
        </div>
      )}
      <Details summary="Details" className="mt-2">
        <p>{lookup.detail}</p>
        {m?.pooled_log2fc != null && (
          <KeyValues
            className="mt-3"
            rows={[
              {
                k: "pooled log2FC",
                v: <span className="font-medium">{fmtLfc(m.pooled_log2fc)}</span>,
              },
              { k: "95% interval", v: `${fmtLfc(m.ci_low)} to ${fmtLfc(m.ci_high)}` },
              { k: "pooled padj", v: fmtP(m.padj) },
              {
                k: "tested in",
                v: (
                  <>
                    {m.n_tested} datasets
                    {m.i2 != null && <span className="text-ink-3"> · I² {fmtNum(m.i2)}</span>}
                  </>
                ),
              },
            ]}
          />
        )}
        {(lookup.driven_by ?? []).length > 0 && (
          <p className="mt-3 text-[12px] text-amber">
            The verdict changes without{" "}
            {(lookup.driven_by ?? []).map((d) => d.split(":")[0]).join(", ")}.
          </p>
        )}
      </Details>
    </Panel>
  );
}

export function RobustGenes({
  title,
  tone,
  rows,
}: {
  title: string;
  tone: "case" | "control";
  rows: GeneMeta[];
}) {
  return (
    <div>
      <ColHead label={<Tag tone={tone}>{title}</Tag>} detail={`top ${Math.min(15, rows.length)}`} />
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
              <Td className="font-mono text-[12px] font-medium">
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
  );
}

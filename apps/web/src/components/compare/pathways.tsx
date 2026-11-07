import type { PathwaySynthesis } from "@/api/generated/types.gen";
import { termLabel } from "@/components/charts/enrichment-bars";
import { Table, Td, Th } from "@/components/ui/table";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

export function PathwaysTable({ pathways, n = 20 }: { pathways: PathwaySynthesis; n?: number }) {
  const members = pathways.members ?? [];
  const terms = [...pathways.terms]
    .sort((a, b) => b.consistency - a.consistency || Math.abs(b.mean_nes) - Math.abs(a.mean_nes))
    .slice(0, n);
  return (
    <Table>
      <thead>
        <tr>
          <Th>Set</Th>
          <Th className="text-right">mean NES</Th>
          <Th className="text-right">consistency</Th>
          <Th className="text-right">sig. FDR</Th>
          {members.map((m) => (
            <Th key={m} className="text-right">
              <span className="accession">{m.split(":")[0]}</span>
            </Th>
          ))}
        </tr>
      </thead>
      <tbody>
        {terms.map((t) => (
          <tr key={t.term}>
            <Td className="text-ink-2">{termLabel(t.term)}</Td>
            <Td
              className={cn(
                "num text-right font-medium",
                t.mean_nes > 0 ? "text-case" : "text-control",
              )}
            >
              {fmtNum(t.mean_nes)}
            </Td>
            <Td className="num text-right">{Math.round(t.consistency * 100)}%</Td>
            <Td className="num text-right">
              {t.n_sig_fdr}/{t.n_members}
            </Td>
            {members.map((m) => {
              const v = t.nes?.[m];
              return (
                <Td
                  key={m}
                  className={cn(
                    "num text-right",
                    v === undefined ? "text-ink-3" : v > 0 ? "text-case" : "text-control",
                  )}
                >
                  {v === undefined ? "—" : fmtNum(v)}
                </Td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

import type { Member } from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Table, Td, Th } from "@/components/ui/table";
import { fmtInt, fmtNum, fmtPct } from "@/lib/format";

export function MemberLedger({ members }: { members: Member[] }) {
  return (
    <Table>
      <thead>
        <tr>
          <Th>Run</Th>
          <Th>Stratum</Th>
          <Th>Tier</Th>
          <Th>Pooled</Th>
          <Th className="text-right">Case / control</Th>
          <Th>Design</Th>
          <Th className="text-right">Sig. genes</Th>
          <Th className="text-right">Concordance</Th>
          <Th className="text-right">Weight</Th>
          <Th>Flags and caveats</Th>
        </tr>
      </thead>
      <tbody>
        {members.map((m) => (
          <tr key={m.label}>
            <Td className="whitespace-nowrap">
              <span className="accession font-medium">{m.gse}</span>
              <div className="font-mono text-[12px] text-ink-2">{m.contrast}</div>
            </Td>
            <Td className="text-[13px]">{m.stratum?.replaceAll("_", " ") ?? "—"}</Td>
            <Td>
              <Badge tone={m.tier === "clean" ? "ok" : "amber"}>{m.tier}</Badge>
            </Td>
            <Td>{m.pooled ? <Badge tone="ok">yes</Badge> : <Badge tone="danger">no</Badge>}</Td>
            <Td className="num text-right">
              {m.n_case} / {m.n_control}
            </Td>
            <Td className="font-mono text-[12px]">
              {m.design}
              {m.pairing !== "none" && <span className="text-ink-3"> · {m.pairing}</span>}
            </Td>
            <Td className="num text-right">{fmtInt(m.n_sig)}</Td>
            <Td className="num text-right">
              {m.mean_concordance == null ? "—" : fmtNum(m.mean_concordance)}
            </Td>
            <Td className="num text-right">
              {m.weight_share == null ? "—" : fmtPct(m.weight_share)}
            </Td>
            <Td className="max-w-[320px] text-[12px]">
              <div className="flex flex-wrap gap-1">
                {(m.flags ?? []).map((f) => (
                  <Badge key={f} tone={f === "labels_reversed" ? "danger" : "amber"}>
                    {f.replaceAll("_", " ")}
                  </Badge>
                ))}
                {(m.qc_flags ?? []).map((f) => (
                  <Badge key={f} tone="amber">
                    {f.replaceAll("_", " ")}
                  </Badge>
                ))}
              </div>
              {(m.qualifications ?? []).length > 0 && (
                <ul className="mt-1 list-disc pl-4 text-ink-2">
                  {(m.qualifications ?? []).map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              )}
            </Td>
          </tr>
        ))}
      </tbody>
    </Table>
  );
}

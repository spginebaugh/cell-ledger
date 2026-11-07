import { ArrowDown, ArrowUp } from "lucide-react";
import { useMemo, useState } from "react";
import type { Contrast, Sample, SampleQc } from "@/api/generated/types.gen";
import { Badge } from "@/components/ui/badge";
import { Table, Td, Th } from "@/components/ui/table";
import { fmtInt, fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";

export type SampleRow = {
  gsm: string;
  arm: "case" | "control" | "other";
  sample: Sample | null;
  qc: SampleQc | null;
};

export function buildRows(samples: Sample[], contrast: Contrast, qc: SampleQc[]): SampleRow[] {
  const byGsm = new Map(samples.map((s) => [s.gsm, s]));
  const qcBy = new Map(qc.map((q) => [q.gsm, q]));
  const arms: [string, "case" | "control"][] = [
    ...contrast.case_gsms.map((g) => [g, "case"] as [string, "case"]),
    ...contrast.control_gsms.map((g) => [g, "control"] as [string, "control"]),
  ];
  return arms.map(([gsm, arm]) => ({
    gsm,
    arm,
    sample: byGsm.get(gsm) ?? null,
    qc: qcBy.get(gsm) ?? null,
  }));
}

type SortKey = "gsm" | "arm" | "library" | "genes" | "confidence" | "flags";

export function SamplesTable({ rows, lowLibrary }: { rows: SampleRow[]; lowLibrary: number }) {
  const [sort, setSort] = useState<{ key: SortKey; dir: 1 | -1 }>({ key: "arm", dir: 1 });
  const sorted = useMemo(() => {
    const val = (r: SampleRow): number | string => {
      switch (sort.key) {
        case "gsm":
          return r.gsm;
        case "arm":
          return r.arm === "case" ? 0 : 1;
        case "library":
          return r.qc?.library_size ?? -1;
        case "genes":
          return r.qc?.detected_genes ?? -1;
        case "confidence":
          return r.sample?.confidence ?? -1;
        case "flags":
          return r.qc?.flags?.length ?? 0;
      }
    };
    return [...rows].sort((a, b) => {
      const va = val(a);
      const vb = val(b);
      const c = va < vb ? -1 : va > vb ? 1 : a.gsm.localeCompare(b.gsm);
      return c * sort.dir;
    });
  }, [rows, sort]);
  const header = (key: SortKey, label: string, className?: string) => (
    <Th
      className={className}
      aria-sort={sort.key === key ? (sort.dir === 1 ? "ascending" : "descending") : "none"}
    >
      <button
        type="button"
        className="inline-flex items-center gap-1 hover:text-ink"
        onClick={() =>
          setSort((s) => (s.key === key ? { key, dir: s.dir === 1 ? -1 : 1 } : { key, dir: 1 }))
        }
      >
        {label}
        {sort.key === key && (sort.dir === 1 ? <ArrowUp size={12} /> : <ArrowDown size={12} />)}
      </button>
    </Th>
  );
  return (
    <Table>
      <thead>
        <tr>
          {header("gsm", "Sample")}
          {header("arm", "Arm")}
          <Th>Harmonized labels</Th>
          <Th>Evidence from GEO</Th>
          {header("confidence", "Conf.", "text-right")}
          {header("library", "Reads", "text-right")}
          {header("genes", "Genes", "text-right")}
          {header("flags", "QC flags")}
        </tr>
      </thead>
      <tbody>
        {sorted.map((r) => {
          const s = r.sample;
          const flagged = (r.qc?.flags?.length ?? 0) > 0 || s?.needs_review;
          const labels = s
            ? [
                s.condition,
                s.tissue,
                s.cell_type,
                s.treatment,
                s.time_point,
                s.donor && `donor ${s.donor}`,
                [s.sex, s.age].filter(Boolean).join(" "),
              ].filter(Boolean)
            : [];
          return (
            <tr key={r.gsm} className={cn(flagged && "bg-amber-soft/40")}>
              <Td className="accession whitespace-nowrap">
                {r.gsm}
                {s?.title && <div className="font-sans text-[12px] text-ink-3">{s.title}</div>}
              </Td>
              <Td>
                <Badge tone={r.arm === "case" ? "case" : "control"}>{r.arm}</Badge>
              </Td>
              <Td className="max-w-[260px] text-[13px]">
                {labels.length ? labels.join(" · ") : <span className="text-ink-3">no labels</span>}
              </Td>
              <Td className="max-w-[320px] text-[13px]">
                {s?.evidence?.length ? (
                  <div className="flex flex-wrap gap-1">
                    {s.evidence.map((e) => (
                      <span
                        key={e}
                        className="rounded-sm bg-surface-2 px-1.5 py-0.5 font-mono text-[12px] text-ink-2"
                      >
                        “{e}”
                      </span>
                    ))}
                  </div>
                ) : (
                  <span className="text-ink-3">—</span>
                )}
              </Td>
              <Td
                className={cn(
                  "num text-right",
                  s && s.confidence != null && s.confidence < 0.7 && "text-amber",
                )}
              >
                {s?.confidence != null ? fmtNum(s.confidence, 2) : "—"}
              </Td>
              <Td
                className={cn(
                  "num text-right",
                  r.qc && r.qc.library_size < lowLibrary && "text-amber",
                )}
              >
                {r.qc ? fmtInt(r.qc.library_size) : "—"}
              </Td>
              <Td className="num text-right">{r.qc ? fmtInt(r.qc.detected_genes) : "—"}</Td>
              <Td>
                <div className="flex flex-wrap gap-1">
                  {(r.qc?.flags ?? []).map((f) => (
                    <Badge key={f} tone="amber">
                      {f.replaceAll("_", " ")}
                    </Badge>
                  ))}
                  {s?.needs_review && <Badge tone="amber">needs review</Badge>}
                  {r.qc?.predicted_sex &&
                    r.qc.reported_sex &&
                    r.qc.predicted_sex !== r.qc.reported_sex && (
                      <Badge tone="amber">
                        sex: reported {r.qc.reported_sex}, predicted {r.qc.predicted_sex}
                      </Badge>
                    )}
                </div>
              </Td>
            </tr>
          );
        })}
      </tbody>
    </Table>
  );
}

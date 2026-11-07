import { useQuery } from "@tanstack/react-query";
import { Download } from "lucide-react";
import { Details } from "@/components/ui/card";
import { fetchFileText } from "@/lib/queries";

const DESCRIPTIONS: Record<string, string> = {
  "report.json": "the canonical report every number here comes from",
  "report.md": "the same report, readable",
  "samples.csv": "sample sheet with QC columns and PCA coordinates",
  "counts.tsv": "reconciled raw counts (genes × samples)",
  "normalized_counts.tsv": "DESeq2 size-factor normalized counts",
  "de_results.tsv": "full differential expression table",
  "enrichment.tsv": "full GSEA table",
  "gene_lookup.csv": "verdicts for the genes asked about",
  "volcano.json.gz": "the table behind the interactive volcano",
  "comparison.json": "the canonical comparison report",
  "comparison.md": "the comparison, readable",
  "gene_table.tsv": "per-gene pooled estimates with every member's effect",
  "pathway_table.tsv": "pathways across members",
  "concordance.tsv": "pairwise Spearman correlation of Wald statistics",
  "members.tsv": "the member ledger",
  "excluded.tsv": "runs that were not pooled and why",
  "pooled_enrichment.tsv": "GSEA on the pooled statistic",
};

export function Downloads({ urls }: { urls: Record<string, string> }) {
  const names = Object.keys(urls).sort(
    (a, b) =>
      (a.startsWith("figures/") ? 1 : 0) - (b.startsWith("figures/") ? 1 : 0) || a.localeCompare(b),
  );
  return (
    <ul className="grid gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2 lg:grid-cols-3">
      {names.map((n) => (
        <li key={n} className="flex items-baseline gap-2">
          <a
            href={urls[n]}
            download
            className="inline-flex items-center gap-1 font-mono text-[13px] underline-offset-2 hover:underline"
            target="_blank"
            rel="noreferrer"
          >
            <Download size={12} className="shrink-0" />
            {n}
          </a>
          {DESCRIPTIONS[n] && <span className="text-[12px] text-ink-3">{DESCRIPTIONS[n]}</span>}
        </li>
      ))}
    </ul>
  );
}

/** report.md / comparison.md rendered inline with a tiny markdown subset (headings, lists, tables, emphasis). */
export function MarkdownFile({ url, summary }: { url: string; summary: string }) {
  const q = useQuery({
    queryKey: ["file", url],
    queryFn: () => fetchFileText(url),
    staleTime: Number.POSITIVE_INFINITY,
  });
  return (
    <Details summary={summary}>
      {q.isPending && <p className="text-sm text-ink-3">Loading…</p>}
      {q.isError && <p className="text-sm text-danger">Could not load the file.</p>}
      {q.data && <div className="prose max-w-[90ch] text-[14px]">{renderMarkdown(q.data)}</div>}
    </Details>
  );
}

export function renderMarkdown(md: string): React.ReactNode[] {
  const lines = md.split("\n");
  const out: React.ReactNode[] = [];
  let i = 0;
  let key = 0;
  const inline = (s: string) => {
    const parts: React.ReactNode[] = [];
    const re = /(\*\*[^*]+\*\*|`[^`]+`)/g;
    let last = 0;
    let m: RegExpExecArray | null = re.exec(s);
    while (m) {
      if (m.index > last) parts.push(s.slice(last, m.index));
      const t = m[0];
      if (t.startsWith("**")) parts.push(<strong key={key++}>{t.slice(2, -2)}</strong>);
      else parts.push(<code key={key++}>{t.slice(1, -1)}</code>);
      last = m.index + t.length;
      m = re.exec(s);
    }
    if (last < s.length) parts.push(s.slice(last));
    return parts;
  };
  while (i < lines.length) {
    const line = lines[i];
    if (/^#{1,3} /.test(line)) {
      const level = line.match(/^#+/)?.[0].length ?? 1;
      const text = line.replace(/^#+ /, "");
      out.push(
        level === 1 ? (
          <h1 key={key++}>{inline(text)}</h1>
        ) : level === 2 ? (
          <h2 key={key++}>{inline(text)}</h2>
        ) : (
          <h3 key={key++}>{inline(text)}</h3>
        ),
      );
      i++;
    } else if (line.startsWith("|")) {
      const rows: string[][] = [];
      while (i < lines.length && lines[i].startsWith("|")) {
        const cells = lines[i]
          .split("|")
          .slice(1, -1)
          .map((c) => c.trim());
        if (!cells.every((c) => /^-+$/.test(c))) rows.push(cells);
        i++;
      }
      const [head, ...body] = rows;
      out.push(
        <table key={key++}>
          <thead>
            <tr>
              {head?.map((c) => (
                <th key={`h-${key++}-${c}`}>{inline(c)}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {body.map((r) => (
              <tr key={`r-${key++}-${r[0]}`}>
                {r.map((c) => (
                  <td key={`c-${key++}-${c}`}>{inline(c)}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>,
      );
    } else if (/^[-*] /.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*] /.test(lines[i])) {
        items.push(lines[i].replace(/^[-*] /, ""));
        i++;
      }
      out.push(
        <ul key={key++} className="list-disc pl-5">
          {items.map((it) => (
            <li key={it}>{inline(it)}</li>
          ))}
        </ul>,
      );
    } else if (line.startsWith("> ")) {
      out.push(
        <blockquote key={key++} className="border-l-2 border-line-2 pl-3 text-ink-2">
          {inline(line.slice(2))}
        </blockquote>,
      );
      i++;
    } else if (line.trim() === "") {
      i++;
    } else {
      const para: string[] = [];
      while (i < lines.length && lines[i].trim() !== "" && !/^(#|\||[-*] |> )/.test(lines[i])) {
        para.push(lines[i]);
        i++;
      }
      out.push(<p key={key++}>{inline(para.join(" "))}</p>);
    }
  }
  return out;
}

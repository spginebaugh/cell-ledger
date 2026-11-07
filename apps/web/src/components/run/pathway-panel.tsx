import { useQuery } from "@tanstack/react-query";
import { ExternalLink, X } from "lucide-react";
import { Dialog as RD } from "radix-ui";
import { useMemo } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { termLabel } from "@/components/charts/enrichment-bars";
import { fdrColor } from "@/components/charts/enrichment-dots";
import { GseaPlot } from "@/components/charts/gsea-plot";
import { Badge, Tag } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/card";
import { fmtInt, fmtNum } from "@/lib/format";
import { decodeGsea, type GseaTable, runningScore } from "@/lib/gsea";
import { fetchFileBytes } from "@/lib/queries";
import { cn } from "@/lib/utils";

export function useGseaTable(url: string | undefined) {
  return useQuery<GseaTable>({
    queryKey: ["gsea", url],
    queryFn: async () => decodeGsea(await fetchFileBytes(url as string)),
    enabled: Boolean(url),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

const fmtFdr = (f: number) => (f < 1e-3 ? "<0.001" : f.toFixed(3));

function msigdbUrl(term: string, library: string): string | null {
  if (!library.toLowerCase().includes("hallmark")) return null;
  const name = `HALLMARK_${termLabel(term).toUpperCase().replaceAll(" ", "_").replaceAll("-", "_")}`;
  return `https://www.gsea-msigdb.org/gsea/msigdb/human/geneset/${name}.html`;
}

/** A side panel for one gene set: the enrichment plot for this run, its scores, and the genes
 * that drive it. Opens when a set is selected on the dot plot or the network. */
export function PathwayPanel({
  term,
  open,
  onClose,
  gseaUrl,
  library,
  fdrThreshold,
  caseLabel,
  controlLabel,
  onPick,
  canPick,
}: {
  term: EnrichmentTerm | null;
  /** lets the caller hide the panel while another drawer has the slot */
  open?: boolean;
  onClose: () => void;
  gseaUrl: string | undefined;
  library: string;
  fdrThreshold: number;
  caseLabel: string;
  controlLabel: string;
  onPick?: (symbol: string) => void;
  canPick?: (symbol: string) => boolean;
}) {
  const isOpen = term !== null && (open ?? true);
  return (
    <RD.Root open={isOpen} onOpenChange={(o) => !o && onClose()} modal={false}>
      <RD.Portal>
        <RD.Content
          onInteractOutside={(e) => e.preventDefault()}
          className="fixed inset-y-0 right-0 z-50 flex w-[min(100vw,560px)] flex-col border-l border-line bg-surface shadow-2xl focus:outline-none"
          aria-describedby={undefined}
        >
          {term && (
            <PanelBody
              key={term.term}
              term={term}
              gseaUrl={gseaUrl}
              library={library}
              fdrThreshold={fdrThreshold}
              caseLabel={caseLabel}
              controlLabel={controlLabel}
              onPick={onPick}
              canPick={canPick}
            />
          )}
          <RD.Close asChild>
            <button
              type="button"
              aria-label="Close pathway panel"
              className="absolute right-4 top-4 inline-grid h-8 w-8 place-items-center rounded-md border border-line-2 bg-surface text-ink-2 hover:border-accent hover:text-accent-ink"
            >
              <X size={15} />
            </button>
          </RD.Close>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

function PanelBody({
  term,
  gseaUrl,
  library,
  fdrThreshold,
  caseLabel,
  controlLabel,
  onPick,
  canPick,
}: {
  term: EnrichmentTerm;
  gseaUrl: string | undefined;
  library: string;
  fdrThreshold: number;
  caseLabel: string;
  controlLabel: string;
  onPick?: (symbol: string) => void;
  canPick?: (symbol: string) => boolean;
}) {
  const gsea = useGseaTable(gseaUrl);
  const up = term.nes > 0;
  const side = up ? caseLabel : controlLabel;
  const link = msigdbUrl(term.term, library);
  const stored = gsea.data?.terms[term.term];
  const leading = useMemo(() => {
    if (!gsea.data || !stored) return null;
    const r = runningScore(gsea.data, stored.hits);
    return r.leading.map((h) => gsea.data?.ranked[h] ?? "");
  }, [gsea.data, stored]);
  const genes = leading ?? term.lead_genes;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="border-b border-line px-5 pb-4 pr-14 pt-5">
        <Tag>Gene set</Tag>
        <RD.Title asChild>
          <h2 className="mt-2 not-italic text-ink">
            <span
              className="font-display text-[26px] font-medium leading-tight"
              style={{ fontVariationSettings: '"opsz" 48' }}
            >
              {termLabel(term.term)}
            </span>
          </h2>
        </RD.Title>
        <div className="mt-3 flex flex-wrap items-center gap-1.5 text-[13px]">
          <Badge tone={up ? "case" : "control"}>enriched in {side}</Badge>
          <Badge className="num normal-case">
            NES {up ? "+" : "−"}
            {Math.abs(term.nes).toFixed(2)}
          </Badge>
          <Badge
            className="num normal-case"
            style={{ borderColor: fdrColor(term.fdr), color: "var(--ink)" }}
            tone={term.fdr < fdrThreshold ? "ok" : "neutral"}
          >
            FDR {fmtFdr(term.fdr)}
          </Badge>
          <Badge className="num normal-case">{fmtInt(term.size)} genes</Badge>
        </div>
        <p className="mt-3 text-[13px] leading-relaxed text-ink-2">
          Genes were ranked from most up in {caseLabel} to most up in {controlLabel}. The score
          walks along that ranking, rising at each gene from this set and falling otherwise. The
          genes of this set bunch up {up ? "near the start" : "near the end"}, so the set as a whole
          is higher in {side}.
        </p>
      </header>

      <div className="space-y-6 px-5 py-5">
        <section>
          <div className="mb-3 flex items-center justify-between gap-2">
            <Tag>Enrichment plot</Tag>
            <span className="text-[12px] text-ink-3">{library.replaceAll("_", " ")}</span>
          </div>
          {!gseaUrl && (
            <p className="text-[13px] text-ink-3">
              This run was analysed before enrichment curves were stored. Re-run it to see the plot.
            </p>
          )}
          {gseaUrl && gsea.isPending && <Skeleton className="h-[300px]" />}
          {gsea.isError && (
            <p className="text-[13px] text-danger">
              The enrichment data could not be loaded: {(gsea.error as Error).message}
            </p>
          )}
          {gsea.data && (
            <GseaPlot
              table={gsea.data}
              term={term.term}
              caseLabel={caseLabel}
              controlLabel={controlLabel}
            />
          )}
          {gsea.data && stored && (
            <p className="num mt-2 text-[12px] text-ink-3">
              {fmtInt(stored.hits.length)} of the set's genes were measured here; the score peaks at
              rank {fmtInt(stored.peak + 1)} of {fmtInt(gsea.data.n)} (ES {fmtNum(stored.es, 2)}).
            </p>
          )}
        </section>

        <section className="border-t border-line pt-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <Tag>{leading ? "Leading edge" : "Leading genes"}</Tag>
            <span className="num text-[12px] text-ink-3">
              {fmtInt(genes.length)} gene{genes.length === 1 ? "" : "s"}
            </span>
          </div>
          <p className="mb-3 text-[13px] text-ink-2">
            {leading
              ? "The genes of this set that sit before the peak: the ones that carry the result."
              : "The genes of this set that contribute most to its score."}
          </p>
          <div className="flex flex-wrap gap-1.5">
            {genes.map((g) => {
              const pickable = Boolean(onPick && (canPick ? canPick(g) : true));
              return (
                <button
                  key={g}
                  type="button"
                  disabled={!pickable}
                  onClick={() => pickable && onPick?.(g)}
                  className={cn(
                    "rounded-md border border-line-2 bg-surface px-2 py-0.5 font-mono text-[12px] text-ink-2",
                    pickable
                      ? "cursor-pointer hover:border-accent hover:text-accent-ink"
                      : "cursor-default opacity-70",
                  )}
                >
                  {g}
                </button>
              );
            })}
          </div>
        </section>

        {link && (
          <footer className="border-t border-line pt-4 text-[13px]">
            <a
              href={link}
              target="_blank"
              rel="noreferrer"
              className="inline-flex items-center gap-1 font-semibold text-accent-ink"
            >
              Read about this set at MSigDB
              <ExternalLink size={13} />
            </a>
          </footer>
        )}
      </div>
    </div>
  );
}

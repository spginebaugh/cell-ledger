import { useQuery } from "@tanstack/react-query";
import type { AnalysisReport } from "@/api/generated/types.gen";
import { ExpressionHeatmap } from "@/components/charts/expression-heatmap";
import { PcaScatter } from "@/components/charts/pca";
import { ColHead, Skeleton } from "@/components/ui/card";
import { decodeHeatmap, type HeatmapTable } from "@/lib/heatmap";
import { fetchFileBytes } from "@/lib/queries";

export function useHeatmapTable(url: string | undefined) {
  return useQuery<HeatmapTable>({
    queryKey: ["heatmap", url],
    queryFn: async () => decodeHeatmap(await fetchFileBytes(url as string)),
    enabled: Boolean(url),
    staleTime: Number.POSITIVE_INFINITY,
  });
}

/** The two pictures that show the groups differ before any statistics: every sample in PCA
 * space, and the top genes as a clustered heatmap. */
export function SamplesPanel({
  report,
  heatmapUrl,
  selected,
  onSelect,
  themeKey,
}: {
  report: AnalysisReport;
  heatmapUrl: string | undefined;
  selected: string | null;
  onSelect: (symbol: string, geneId: string) => void;
  themeKey: string;
}) {
  const heat = useHeatmapTable(heatmapUrl);
  const caseLabel = report.contrast.case_label;
  const controlLabel = report.contrast.control_label;
  const hasHeat = Boolean(heatmapUrl);
  return (
    <div
      className={
        hasHeat
          ? "grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:gap-x-8"
          : "grid gap-6 lg:max-w-3xl"
      }
    >
      {report.qc && (
        <div className="min-w-0">
          <ColHead
            label="Every sample"
            detail={
              report.qc.pca
                ? `PCA on the ${report.qc.pca.n_genes_used.toLocaleString()} most variable genes`
                : undefined
            }
          />
          <PcaScatter qc={report.qc} caseLabel={caseLabel} controlLabel={controlLabel} />
          <p className="mt-3 text-[12px] text-ink-3">
            The PCA was never told which samples are {caseLabel}. If the two colours fall into
            separate clouds, the groups differ in their overall expression, not just in a few genes.
          </p>
        </div>
      )}
      {hasHeat && (
        <div className="min-w-0 border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
          <ColHead
            label="Top genes, every sample"
            detail={
              heat.data ? `${heat.data.nGenes} genes × ${heat.data.nSamples} samples` : undefined
            }
          />
          {heat.isPending && <Skeleton className="h-[460px]" />}
          {heat.isError && (
            <p className="text-sm text-danger">
              Could not load the heatmap: {(heat.error as Error).message}
            </p>
          )}
          {heat.data && (
            <ExpressionHeatmap
              table={heat.data}
              caseLabel={caseLabel}
              controlLabel={controlLabel}
              selected={selected}
              onSelect={onSelect}
              themeKey={themeKey}
            />
          )}
          <p className="mt-3 text-[12px] text-ink-3">
            Each row is one of the most significant genes from the test below, each column one
            sample; colour is how far that sample sits from the gene's average. Because the genes
            were chosen by that test, a split between the arms is expected; what this shows is
            whether every sample follows it. Rows and columns are ordered by clustering, the bar on
            top names the arms. Click a gene to open it.
          </p>
        </div>
      )}
    </div>
  );
}

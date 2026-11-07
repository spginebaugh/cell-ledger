import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronLeft, MousePointerClick } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { EnrichmentBars } from "@/components/charts/enrichment-bars";
import { EnrichmentDots } from "@/components/charts/enrichment-dots";
import { PathwayNetwork } from "@/components/charts/pathway-network";
import { GenePanel, type SelectedGene } from "@/components/gene/gene-panel";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { AnswerPanel, StatusBanner } from "@/components/run/answer-panel";
import { ComparisonPanel } from "@/components/run/design-panel";
import { Downloads, MarkdownFile } from "@/components/run/downloads";
import { PathwayPanel } from "@/components/run/pathway-panel";
import { SamplesPanel } from "@/components/run/samples-panel";
import { LiveStepper } from "@/components/run/steps";
import { useVolcanoTable, VolcanoPanel } from "@/components/run/volcano-panel";
import { StatusChip } from "@/components/ui/badge";
import { ColHead, Details, ErrorBox, Panel, Pill, Section, Skeleton } from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useDatasets, useRun, useSession } from "@/lib/queries";
import { useTheme } from "@/lib/theme";
import { runRoute } from "@/router";

export function RunPage() {
  const { sessionId, gse, contrast } = runRoute.useParams();
  const run = useRun(sessionId, gse, contrast);
  const session = useSession(sessionId);
  const { resolved } = useTheme();
  const [term, setTerm] = useState<EnrichmentTerm | null>(null);
  const [focus, setFocus] = useState<string | null>(null);

  // The open gene panel is addressed by ?gene=SYMBOL so a gene can be linked to. The GeneID
  // is kept alongside when the selection came from a click; a linked symbol is resolved.
  const { gene: geneParam } = runRoute.useSearch();
  const navigate = useNavigate({ from: runRoute.fullPath });
  const [selectedEntrez, setSelectedEntrez] = useState<{ symbol: string; entrez: string } | null>(
    null,
  );
  const selected: SelectedGene | null = useMemo(
    () =>
      geneParam
        ? {
            symbol: geneParam,
            entrez:
              selectedEntrez?.symbol.toUpperCase() === geneParam.toUpperCase()
                ? selectedEntrez.entrez
                : null,
          }
        : null,
    [geneParam, selectedEntrez],
  );
  const selectGene = useCallback(
    (symbol: string | null, entrez?: string) => {
      setSelectedEntrez(symbol && entrez ? { symbol, entrez } : null);
      navigate({
        search: (prev) => ({ ...prev, gene: symbol ?? undefined }),
        replace: true,
        resetScroll: false,
      });
    },
    [navigate],
  );

  useEffect(() => {
    document.title = `${gse} ${contrast.replaceAll("_", " ")} · cell ledger`;
  }, [gse, contrast]);

  const view = run.data;
  const report = view?.report ?? null;
  const datasets = useDatasets(sessionId, session.isSuccess);
  const proposal = datasets.data?.find((d) => d.gse === gse)?.proposal ?? null;
  const urls = view?.urls ?? {};
  const nFiles = Object.keys(urls).length;

  // Shared with VolcanoPanel through the query cache; used to resolve a partner symbol to
  // its GeneID when the panel asks to jump to it.
  const volcano = useVolcanoTable(urls["volcano.json.gz"]);
  const geneIdBySymbol = useMemo(() => {
    const m = new Map<string, string>();
    volcano.data?.symbol.forEach((s, i) => {
      if (s) m.set(s.toUpperCase(), volcano.data?.geneId[i] ?? "");
    });
    return m;
  }, [volcano.data]);
  const canPick = useCallback((s: string) => geneIdBySymbol.has(s.toUpperCase()), [geneIdBySymbol]);
  const pick = useCallback(
    (s: string) => selectGene(s, geneIdBySymbol.get(s.toUpperCase())),
    [selectGene, geneIdBySymbol],
  );

  const focusGene = (symbol: string | null) => {
    setFocus(symbol);
    if (symbol) {
      document.getElementById("volcano")?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const de = report?.de?.summary;
  const deLede = de
    ? `DESeq2${de.blocking ? `, blocked by ${de.blocking}` : ""}. ${fmtInt(de.n_sig)} genes differ at padj < ${de.alpha}; at |log2FC| ≥ ${de.lfc_threshold.toFixed(2)}, ${fmtInt(de.n_up_lfc)} are higher in case and ${fmtInt(de.n_down_lfc)} higher in control. Adjust the thresholds and the counts follow.`
    : "Differential expression did not run for this contrast.";

  return (
    <>
      <TopBar sessionId={sessionId} />
      <GenePanel
        gene={selected}
        onClose={() => selectGene(null)}
        onPick={pick}
        canPick={canPick}
        themeKey={resolved}
      />
      {report?.enrichment && (
        <PathwayPanel
          term={term}
          // a gene opened from the pathway panel takes the drawer; the set comes back on close
          open={selected === null}
          onClose={() => setTerm(null)}
          gseaUrl={urls["gsea.json.gz"]}
          library={report.enrichment.library}
          fdrThreshold={report.enrichment.fdr_threshold}
          caseLabel={report.contrast.case_label}
          controlLabel={report.contrast.control_label}
          onPick={pick}
          canPick={canPick}
        />
      )}
      <Page>
        <div className="flex items-center justify-between gap-2 text-[13px]">
          <Link
            to="/s/$sessionId"
            params={{ sessionId }}
            className="inline-flex items-center gap-0.5 font-semibold text-ink no-underline hover:text-accent-ink"
          >
            <ChevronLeft size={14} strokeWidth={2.5} />
            Back
          </Link>
          <span className="font-semibold">
            Dataset <span className="accession font-bold text-accent-ink">{gse}</span>
          </span>
        </div>
        {run.isPending && (
          <div className="mt-4 space-y-4">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-28" />
            <Skeleton className="h-64" />
          </div>
        )}
        {run.isError && (
          <div className="mt-4">
            <ErrorBox title="Could not load this run">{errorMessage(run.error)}</ErrorBox>
          </div>
        )}
        {view && (
          <>
            <div className="mt-3">
              <h1 className="w-full">
                {report ? (
                  <>
                    {report.contrast.case_label} <span className="font-normal text-ink-3">vs</span>{" "}
                    {report.contrast.control_label}
                  </>
                ) : (
                  contrast.replaceAll("_", " ")
                )}
              </h1>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
                <div className="grid min-w-0 justify-items-start gap-2">
                  <Pill label="Contrast" mono>
                    {contrast}
                  </Pill>
                  {session.data?.question && <Pill label="Asked">“{session.data.question}”</Pill>}
                </div>
                <StatusChip status={view.status} busy={view.status === "running"} />
              </div>
            </div>

            {view.status === "running" && (
              <Panel className="mt-6 max-w-xl p-5">
                <h3>The pipeline is running</h3>
                <p className="mt-1 text-sm text-ink-2">
                  This page refreshes itself and fills in as the steps complete.
                </p>
                <div className="mt-4">
                  <LiveStepper progress={view.progress} startedAt={view.started_at} />
                </div>
              </Panel>
            )}

            {view.status !== "running" && (
              <>
                <div className="mt-6">
                  <StatusBanner report={report} error={view.error} status={view.status} />
                </div>

                {report && (
                  <>
                    <Section
                      title="The Answer"
                      info="A verdict for each gene the question named, drawn from this dataset alone. Select a gene to locate it in the plots, or click a point on the volcano to open its gene."
                    >
                      <AnswerPanel report={report} onFocus={focusGene} focus={focus} />
                      {report.markers && (
                        <p className="num mt-3 text-[13px] text-ink-2">
                          Marker panel: {report.markers.n_recovered_sig} of{" "}
                          {report.markers.n_expected} expected markers recovered with the expected
                          sign; {report.markers.n_in_top_n} in the top {report.markers.top_n}.
                        </p>
                      )}
                    </Section>

                    <Section
                      title="The Comparison"
                      info="The two arms of the comparison, and the reasoning that chose them."
                    >
                      <ComparisonPanel report={report} proposal={proposal} />
                    </Section>

                    {report.qc && (
                      <Section
                        title="The Samples"
                        info="Every sample at once. The PCA is the blind check: it uses the most variable genes and was never told the arms. The heatmap shows the differential-expression result at per-sample resolution: its genes are the top hits, so the question it answers is whether every sample follows the group pattern or a few drive it."
                      >
                        <Panel>
                          <SamplesPanel
                            report={report}
                            heatmapUrl={report.de ? urls["heatmap.json.gz"] : undefined}
                            selected={selected?.symbol ?? null}
                            onSelect={(symbol, geneId) => selectGene(symbol, geneId)}
                            themeKey={resolved}
                          />
                        </Panel>
                      </Section>
                    )}

                    {report.de && (
                      <Section title="Differential Expression" info={deLede}>
                        <Panel>
                          <div className="min-w-0">
                            <div id="volcano" className="min-w-0">
                              <div className="-mb-2">
                                <ColHead label="Volcano" />
                              </div>
                              <p
                                className="mb-4 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-bold text-white"
                                style={{ background: "#7b3294" }}
                              >
                                <MousePointerClick size={15} strokeWidth={2.25} aria-hidden />
                                Click any gene to learn more
                              </p>
                              <VolcanoPanel
                                url={urls["volcano.json.gz"]}
                                alpha0={report.de.summary.alpha}
                                lfc0={report.de.summary.lfc_threshold}
                                term={term}
                                focus={focus}
                                onFocus={focusGene}
                                selected={selected?.symbol ?? null}
                                onSelect={(symbol, geneId) => selectGene(symbol, geneId)}
                                themeKey={resolved}
                              />
                            </div>
                            {report.enrichment && (
                              <div className="mt-6 min-w-0 border-t border-line pt-5">
                                <ColHead
                                  label="Pathways"
                                  detail={`${report.enrichment.n_sig_fdr} of ${report.enrichment.n_terms} sets at FDR < ${report.enrichment.fdr_threshold}`}
                                />
                                <EnrichmentDots
                                  terms={report.enrichment.top}
                                  selected={term?.term ?? null}
                                  onSelect={setTerm}
                                  caseLabel={report.contrast.case_label}
                                  controlLabel={report.contrast.control_label}
                                />
                                <p className="mt-3 text-[12px] text-ink-3">
                                  Each circle is a gene set. Further from the centre line is a
                                  stronger shift, a bigger circle is a bigger set, and a darker
                                  circle is a surer result. Click one to open its enrichment plot
                                  and mark its leading genes on the volcano.
                                </p>
                                <Details summary="As a table" className="mt-3">
                                  <EnrichmentBars
                                    terms={report.enrichment.top}
                                    selected={term?.term ?? null}
                                    onSelect={setTerm}
                                  />
                                </Details>
                              </div>
                            )}
                          </div>
                        </Panel>
                      </Section>
                    )}

                    {report.enrichment && report.enrichment.top.length > 0 && (
                      <Section
                        title="How the Pathways Connect"
                        info="The strongest gene sets as hubs, joined to the genes that drive them. Sets that share genes pull together. Selecting a set here also marks its genes on the volcano."
                      >
                        <Panel>
                          <PathwayNetwork
                            terms={report.enrichment.top}
                            selected={term?.term ?? null}
                            onSelectTerm={setTerm}
                            onSelectGene={pick}
                            canPick={canPick}
                          />
                        </Panel>
                      </Section>
                    )}
                  </>
                )}

                {nFiles > 0 && (
                  <Section
                    title="Files"
                    description={
                      <>
                        <span className="num">
                          {nFiles} file{nFiles === 1 ? "" : "s"}
                        </span>
                        <span className="mx-1 text-ink-3">|</span>
                        <em className="text-ink-3">Links valid for one day</em>
                      </>
                    }
                  >
                    <Panel>
                      <Downloads urls={urls} />
                      {urls["report.md"] && (
                        <div className="mt-4 border-t border-line pt-3">
                          <MarkdownFile url={urls["report.md"]} summary="Read report.md inline" />
                        </div>
                      )}
                    </Panel>
                  </Section>
                )}
              </>
            )}
          </>
        )}
        <Footer />
      </Page>
    </>
  );
}

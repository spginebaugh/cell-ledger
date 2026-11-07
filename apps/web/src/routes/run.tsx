import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { useEffect, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { EnrichmentBars } from "@/components/charts/enrichment-bars";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { AnswerPanel, StatusBanner } from "@/components/run/answer-panel";
import { ComparisonPanel } from "@/components/run/design-panel";
import { Downloads, MarkdownFile } from "@/components/run/downloads";
import { LiveStepper } from "@/components/run/steps";
import { VolcanoPanel } from "@/components/run/volcano-panel";
import { StatusChip } from "@/components/ui/badge";
import { ColHead, ErrorBox, Panel, Pill, Section, Skeleton } from "@/components/ui/card";
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

  useEffect(() => {
    document.title = `${gse} ${contrast.replaceAll("_", " ")} · cell ledger`;
  }, [gse, contrast]);

  const view = run.data;
  const report = view?.report ?? null;
  const datasets = useDatasets(sessionId, session.isSuccess);
  const proposal = datasets.data?.find((d) => d.gse === gse)?.proposal ?? null;
  const urls = view?.urls ?? {};
  const nFiles = Object.keys(urls).length;

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
                      info="A verdict for each gene the question named, drawn from this dataset alone. Select a gene to locate it in the plots."
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

                    {report.de && (
                      <Section title="Differential Expression" info={deLede}>
                        <Panel>
                          <div className="grid gap-6 lg:grid-cols-[minmax(0,3fr)_minmax(0,2fr)] lg:gap-x-8">
                            <div id="volcano" className="min-w-0">
                              <ColHead label="Volcano" />
                              <VolcanoPanel
                                url={urls["volcano.json.gz"]}
                                alpha0={report.de.summary.alpha}
                                lfc0={report.de.summary.lfc_threshold}
                                term={term}
                                focus={focus}
                                onFocus={focusGene}
                                themeKey={resolved}
                              />
                            </div>
                            {report.enrichment && (
                              <div className="min-w-0 border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                                <ColHead
                                  label="Pathways"
                                  detail={`${report.enrichment.n_sig_fdr} of ${report.enrichment.n_terms} sets at FDR < ${report.enrichment.fdr_threshold}`}
                                />
                                <EnrichmentBars
                                  terms={report.enrichment.top}
                                  selected={term?.term ?? null}
                                  onSelect={setTerm}
                                />
                                <p className="mt-3 text-[12px] text-ink-3">
                                  Select a set to mark its leading genes on the volcano. A positive
                                  score means the set is enriched in {report.contrast.case_label}.
                                </p>
                              </div>
                            )}
                          </div>
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

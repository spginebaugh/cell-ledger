import { Link } from "@tanstack/react-router";
import { useEffect, useMemo, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { EnrichmentBars } from "@/components/charts/enrichment-bars";
import { LibrarySizes } from "@/components/charts/library-sizes";
import { PcaScatter } from "@/components/charts/pca";
import { StripPlot } from "@/components/charts/strip-plot";
import { Page, TopBar } from "@/components/layout/top-bar";
import { AnswerPanel, StatusBanner } from "@/components/run/answer-panel";
import { DesignPanel } from "@/components/run/design-panel";
import { Downloads, MarkdownFile } from "@/components/run/downloads";
import { buildRows, SamplesTable } from "@/components/run/samples-table";
import { LiveStepper, StepTimeline } from "@/components/run/steps";
import { VolcanoPanel } from "@/components/run/volcano-panel";
import { Decisions } from "@/components/session/pipeline-view";
import { Badge } from "@/components/ui/badge";
import { Card, Details, ErrorBox, Section, Skeleton } from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { fmtInt, statusLabel, statusTone, verdictLabel, verdictTone } from "@/lib/format";
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
    document.title = `${gse} ${contrast.replaceAll("_", " ")} · cell-ledger`;
  }, [gse, contrast]);

  const view = run.data;
  const report = view?.report ?? null;
  const design = view?.design ?? null;
  const datasets = useDatasets(sessionId, session.isSuccess);
  const proposal = datasets.data?.find((d) => d.gse === gse)?.proposal ?? null;
  const urls = view?.urls ?? {};

  const sampleRows = useMemo(() => {
    if (!report || !design) return [];
    return buildRows(design.samplesheet.samples, report.contrast, report.qc?.samples ?? []);
  }, [report, design]);

  const labelsByGsm = useMemo(() => {
    const m = new Map<string, string[]>();
    for (const r of sampleRows) {
      const s = r.sample;
      if (s)
        m.set(
          r.gsm,
          [s.condition, s.tissue, s.treatment, s.donor && `donor ${s.donor}`].filter(
            (v): v is string => Boolean(v),
          ),
        );
    }
    return m;
  }, [sampleRows]);

  const focusGene = (symbol: string | null) => {
    setFocus(symbol);
    if (symbol) {
      const el = document.getElementById(`gene-${symbol.toUpperCase()}`);
      el?.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  };

  const lowLibrary = Number(
    (report?.params as Record<string, unknown> | undefined)?.low_library_size ?? 1e6,
  );

  return (
    <>
      <TopBar sessionId={sessionId} />
      <Page>
        <nav className="text-[13px] text-ink-2">
          <Link to="/s/$sessionId" params={{ sessionId }} className="hover:underline">
            Session
          </Link>
          <span className="mx-1.5 text-ink-3">/</span>
          <span className="accession">{gse}</span>
        </nav>
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
            <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-[70ch]">
                <h1>
                  {report ? (
                    <>
                      {report.contrast.case_label} <span className="text-ink-3">vs</span>{" "}
                      {report.contrast.control_label}
                    </>
                  ) : (
                    contrast.replaceAll("_", " ")
                  )}
                </h1>
                <p className="mt-2 text-ink-2">
                  <span className="accession">{gse}</span> · contrast{" "}
                  <span className="font-mono text-[14px]">{contrast}</span>
                  {session.data?.question && <> · asked: “{session.data.question}”</>}
                </p>
              </div>
              <Badge tone={statusTone(view.status)} className="text-[13px]">
                {statusLabel(view.status)}
              </Badge>
            </div>

            {view.status === "running" && (
              <Card className="mt-6 max-w-xl p-5">
                <h3>The pipeline is running</h3>
                <p className="mt-1 text-sm text-ink-2">
                  This page refreshes itself and fills in as the steps complete.
                </p>
                <div className="mt-4">
                  <LiveStepper progress={view.progress} startedAt={view.started_at} />
                </div>
              </Card>
            )}

            {view.status !== "running" && (
              <>
                <div className="mt-6">
                  <StatusBanner report={report} error={view.error} status={view.status} />
                </div>

                {report && (
                  <>
                    <Section
                      title="The answer"
                      description="One card per gene asked about, from this dataset alone. Click a card to find the gene in the plots below."
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
                      title="The comparison"
                      description="What was compared with what, and how the model was set up."
                    >
                      <DesignPanel report={report} design={design} />
                      {proposal && (
                        <div className="mt-4">
                          <Decisions proposal={proposal} defaultOpen />
                        </div>
                      )}
                    </Section>

                    {sampleRows.length > 0 && (
                      <Section
                        title="Samples and their evidence"
                        description="Every label was copied from the GEO record; the quoted text is the proof. Flagged rows are tinted."
                      >
                        <SamplesTable rows={sampleRows} lowLibrary={lowLibrary} />
                      </Section>
                    )}

                    {report.qc && (
                      <Section
                        title="Quality control"
                        description={
                          report.qc.flags?.length
                            ? `Dataset flags: ${report.qc.flags.join(", ")}`
                            : "No dataset-level flags were raised."
                        }
                      >
                        <div className="grid gap-6 lg:grid-cols-2">
                          <Card className="p-4">
                            <h3>Library size per sample</h3>
                            <div className="mt-3">
                              <LibrarySizes
                                rows={report.qc.samples.map((s) => ({
                                  gsm: s.gsm,
                                  arm: s.arm,
                                  librarySize: s.library_size,
                                  flags: s.flags ?? [],
                                }))}
                                threshold={lowLibrary}
                              />
                            </div>
                          </Card>
                          {report.qc.pca && (
                            <Card className="p-4">
                              <h3>Principal components</h3>
                              <p className="mt-0.5 text-[12px] text-ink-3">
                                log-CPM of the most variable genes; flagged samples are labelled
                              </p>
                              <div className="mt-3">
                                <PcaScatter
                                  points={report.qc.samples.map((s) => {
                                    const c = report.qc?.pca?.coords[s.gsm] ?? [0, 0];
                                    return {
                                      gsm: s.gsm,
                                      arm: s.arm,
                                      x: c[0],
                                      y: c[1],
                                      flags: s.flags ?? [],
                                      labels: labelsByGsm.get(s.gsm) ?? [],
                                    };
                                  })}
                                  variance={report.qc.pca.variance_ratio}
                                  armR2={report.qc.pca.arm_r2_pc1}
                                />
                              </div>
                            </Card>
                          )}
                        </div>
                      </Section>
                    )}

                    {report.de && (
                      <Section
                        title="Differential expression"
                        description={`${fmtInt(report.de.summary.n_sig)} genes at padj < ${report.de.summary.alpha}: ${fmtInt(report.de.summary.n_up)} higher in case, ${fmtInt(report.de.summary.n_down)} higher in control. Move the thresholds to see how the counts respond.`}
                      >
                        <div className="grid gap-6 xl:grid-cols-[3fr_2fr]">
                          <Card className="p-4">
                            <VolcanoPanel
                              url={urls["volcano.json.gz"]}
                              alpha0={report.de.summary.alpha}
                              lfc0={report.de.summary.lfc_threshold}
                              term={term}
                              focus={focus}
                              onFocus={focusGene}
                              themeKey={resolved}
                            />
                          </Card>
                          {report.enrichment && (
                            <Card className="p-4">
                              <h3>
                                Pathways (GSEA, {report.enrichment.library.replaceAll("_", " ")})
                              </h3>
                              <p className="mt-0.5 text-[12px] text-ink-3">
                                {report.enrichment.n_sig_fdr} of {report.enrichment.n_terms} sets at
                                FDR &lt; {report.enrichment.fdr_threshold}; click a bar to light up
                                its genes on the volcano
                              </p>
                              <div className="mt-3">
                                <EnrichmentBars
                                  terms={report.enrichment.top}
                                  selected={term?.term ?? null}
                                  onSelect={setTerm}
                                />
                              </div>
                            </Card>
                          )}
                        </div>
                      </Section>
                    )}

                    {(report.gene_expression ?? []).length > 0 && (
                      <Section
                        title="Genes of interest, sample by sample"
                        description="Log2 normalized counts for each fitted observation; the bar is the arm mean. Repeated samples of one donor or block were summed first, as in the fit."
                      >
                        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
                          {(report.gene_expression ?? []).map((g) => {
                            const lookup = (report.gene_lookup ?? []).find(
                              (r) => r.gene_id === g.gene_id,
                            );
                            const arms = new Map<string, "case" | "control">([
                              ...report.contrast.case_gsms.map((x) => [x, "case"] as const),
                              ...report.contrast.control_gsms.map((x) => [x, "control"] as const),
                            ]);
                            const sym = g.symbol ?? g.gene_id;
                            const isFocus = focus?.toUpperCase() === sym.toUpperCase();
                            return (
                              <Card
                                key={g.gene_id}
                                id={`gene-${sym.toUpperCase()}`}
                                className={isFocus ? "border-ink p-4" : "p-4"}
                              >
                                <div className="flex items-center justify-between gap-2">
                                  <h3>{sym}</h3>
                                  {lookup && (
                                    <Badge tone={verdictTone(lookup.verdict)}>
                                      {verdictLabel(lookup.verdict)}
                                    </Badge>
                                  )}
                                </div>
                                <div className="mt-2">
                                  <StripPlot
                                    points={Object.entries(g.values).flatMap(([unit, v]) => {
                                      // Repeated samples per block and arm were summed before
                                      // the fit into units named `<block>|<arm>`; the plot shows
                                      // what was fitted, so those appear as one point each.
                                      const arm =
                                        arms.get(unit) ?? unit.slice(unit.lastIndexOf("|") + 1);
                                      if (arm !== "case" && arm !== "control") return [];
                                      const members = report.de?.summary.collapsed?.[unit];
                                      return [{ gsm: unit, arm, value: v, members }];
                                    })}
                                    caseLabel={report.contrast.case_label}
                                    controlLabel={report.contrast.control_label}
                                  />
                                </div>
                              </Card>
                            );
                          })}
                        </div>
                      </Section>
                    )}

                    <Section
                      title="How it ran"
                      description="Every step with its parameters and timing. The fingerprint identifies this exact input, design, parameter set and code version."
                    >
                      <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
                        <Card className="p-4">
                          <StepTimeline steps={report.steps ?? []} />
                        </Card>
                        <div className="space-y-3">
                          <Details summary="Software versions" defaultOpen>
                            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 font-mono text-[12px]">
                              {Object.entries(report.versions).map(([k, v]) => (
                                <div key={k} className="contents">
                                  <dt className="text-ink-2">{k}</dt>
                                  <dd>{v}</dd>
                                </div>
                              ))}
                            </dl>
                          </Details>
                          <Details summary="Fingerprint and parameters">
                            <p className="break-all font-mono text-[12px]">
                              {report.fingerprint ?? "no fingerprint"}
                            </p>
                            <pre className="mt-2 max-h-64 overflow-auto rounded bg-surface-2 p-2 text-[11px]">
                              {JSON.stringify(report.params, null, 1)}
                            </pre>
                          </Details>
                        </div>
                      </div>
                    </Section>
                  </>
                )}

                {Object.keys(urls).length > 0 && (
                  <Section
                    title="Files"
                    description="Everything the run wrote, straight from storage. Links are valid for a day."
                  >
                    <Downloads urls={urls} />
                    {urls["report.md"] && (
                      <div className="mt-4">
                        <MarkdownFile url={urls["report.md"]} summary="Read report.md inline" />
                      </div>
                    )}
                  </Section>
                )}
              </>
            )}
          </>
        )}
      </Page>
    </>
  );
}

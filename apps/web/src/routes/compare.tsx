import { Link } from "@tanstack/react-router";
import { ChevronLeft, MousePointerClick } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { AgreementWall } from "@/components/charts/agreement-wall";
import { EnrichmentBars } from "@/components/charts/enrichment-bars";
import { EnrichmentDots } from "@/components/charts/enrichment-dots";
import { ConcordanceHeatmap } from "@/components/charts/heatmap";
import { PathwayMatrix } from "@/components/charts/pathway-matrix";
import { PathwayNetwork } from "@/components/charts/pathway-network";
import { hasPerMemberEffects, ReplicationStrip } from "@/components/charts/replication-strip";
import { GeneAcrossCard, RobustGenes } from "@/components/compare/genes";
import { MemberLedger } from "@/components/compare/ledger";
import { PathwaysTable } from "@/components/compare/pathways";
import { PooledLoading, PooledVolcanoPanel, usePooledTable } from "@/components/compare/pooled";
import { GenePanel, type SelectedGene } from "@/components/gene/gene-panel";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { Downloads, MarkdownFile } from "@/components/run/downloads";
import { StatusChip, Tag } from "@/components/ui/badge";
import {
  ColHead,
  Details,
  ErrorBox,
  Notice,
  Panel,
  Pill,
  Section,
  Skeleton,
} from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { fmtInt } from "@/lib/format";
import { useComparison } from "@/lib/queries";
import { useTheme } from "@/lib/theme";
import { compareRoute } from "@/router";

const POOLED_FILE = "pooled_genes.json.gz";

export function ComparePage() {
  const { sessionId, name } = compareRoute.useParams();
  const q = useComparison(sessionId, name);
  const { resolved } = useTheme();
  const [term, setTerm] = useState<EnrichmentTerm | null>(null);
  const [selected, setSelected] = useState<SelectedGene | null>(null);
  useEffect(() => {
    document.title = `${name.replaceAll("_", " ")} · cell ledger`;
  }, [name]);
  const view = q.data;
  const rep = view?.report ?? null;
  const memberRows = rep?.members ?? [];
  const members = memberRows.map((m) => m.label);
  const warnings = rep?.warnings ?? [];
  const questions = rep?.questions ?? [];
  const lookups = rep?.gene_lookup ?? [];
  const excluded = rep?.excluded ?? [];
  const urls = view?.urls ?? {};
  const nFiles = Object.keys(urls).length;
  const perMember =
    rep?.genes != null && hasPerMemberEffects([...rep.genes.top_up, ...rep.genes.top_down]);
  const nPooled = memberRows.filter((m) => m.pooled).length;

  // The browser-side gene table: every pooled gene in every dataset. Comparisons written
  // before it existed have no file; the page then keeps to the report alone.
  const pooled = usePooledTable(view?.status === "running" ? undefined : urls[POOLED_FILE]);
  const geneIdBySymbol = useMemo(() => {
    const m = new Map<string, string>();
    pooled.data?.symbol.forEach((s, i) => {
      if (s) m.set(s.toUpperCase(), pooled.data?.geneId[i] ?? "");
    });
    return m;
  }, [pooled.data]);
  const canPick = useCallback((s: string) => geneIdBySymbol.has(s.toUpperCase()), [geneIdBySymbol]);
  const selectGene = useCallback(
    (symbol: string | null, entrez?: string) =>
      setSelected(symbol ? { symbol, entrez: entrez ?? null } : null),
    [],
  );
  const pick = useCallback(
    (s: string) => selectGene(s, geneIdBySymbol.get(s.toUpperCase())),
    [selectGene, geneIdBySymbol],
  );
  const asked = useMemo(
    () => lookups.map((g) => g.symbol ?? g.query).filter((s): s is string => Boolean(s)),
    [lookups],
  );
  const pooledEnrichment = rep?.pooled_enrichment ?? null;

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
            Comparison <span className="font-mono font-bold text-accent-ink">{name}</span>
          </span>
        </div>
        {q.isPending && (
          <div className="mt-4 space-y-4">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-40" />
          </div>
        )}
        {q.isError && (
          <div className="mt-4">
            <ErrorBox title="Could not load this comparison">{errorMessage(q.error)}</ErrorBox>
          </div>
        )}
        {view && (
          <>
            <div className="mt-3">
              <h1 className="w-full">{view.request.question}</h1>
              <div className="mt-5 flex flex-wrap items-center justify-between gap-4">
                <div className="grid min-w-0 justify-items-start gap-2">
                  <Pill label="Case">{view.request.case_label}</Pill>
                  <Pill label="Control">{view.request.control_label}</Pill>
                  <Pill label="Datasets">{view.request.members.length} pooled</Pill>
                </div>
                <StatusChip status={view.status} busy={view.status === "running"} />
              </div>
            </div>

            {view.status === "running" && (
              <Panel className="mt-6 max-w-xl p-5">
                <h3>Pooling the runs</h3>
                <p className="mt-1 text-[13px] text-ink-2">
                  Random-effects meta-analysis per gene, concordance, pathways and pooled GSEA. This
                  takes a minute.
                </p>
              </Panel>
            )}
            {view.status === "failed" && (
              <div className="mt-6">
                <Notice tone="danger" title="The comparison failed">
                  {view.error ?? rep?.error ?? "no details"}
                </Notice>
              </div>
            )}

            {rep && view.status !== "running" && (
              <>
                <div className="mt-6 space-y-3">
                  {rep.status === "insufficient" && (
                    <Notice tone="amber" title="Insufficient: Not Enough Datasets Pooled">
                      <ul>
                        {warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </Notice>
                  )}
                  {questions.length > 0 && (
                    <Notice tone="amber" title="Decide These Before Trusting the Pool">
                      <ul>
                        {questions.map((x) => (
                          <li key={x}>{x}</li>
                        ))}
                      </ul>
                    </Notice>
                  )}
                  {rep.status === "complete" && rep.genes && (
                    <Notice
                      tone="ok"
                      title={`Complete: ${fmtInt(rep.genes.n_robust)} Genes Replicate`}
                    >
                      <p className="num">
                        {fmtInt(rep.genes.n_robust_up)} higher in case,{" "}
                        {fmtInt(rep.genes.n_robust_down)} higher in control, out of{" "}
                        {fmtInt(rep.genes.n_genes_pooled)} genes pooled across {nPooled} datasets.
                      </p>
                      <p>
                        A gene is robust when its pooled padj &lt; {rep.genes.alpha}, its sign
                        agrees in at least {Math.round(rep.genes.sign_consistency * 100)}% of
                        datasets and it is significant in at least{" "}
                        {Math.round(rep.genes.min_replication * 100)}%.
                      </p>
                    </Notice>
                  )}
                  {rep.status === "complete" && warnings.length > 0 && (
                    <Details
                      summary={`${warnings.length} warning${warnings.length === 1 ? "" : "s"}`}
                    >
                      <ul className="list-disc pl-5">
                        {warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </Details>
                  )}
                </div>

                {lookups.length > 0 && (
                  <Section
                    title="The Answer, Across Datasets"
                    info="Each gene's estimate per dataset (a point and its 95% interval, sized by the samples behind it) and the pooled estimate (diamond). Every point on the same side of the line is the same answer from every lab."
                  >
                    <div className="grid gap-3">
                      <GeneAcrossCard lookup={lookups[0]} members={members} hero />
                      {lookups.length > 1 && (
                        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                          {lookups.slice(1).map((g) => (
                            <GeneAcrossCard key={g.query} lookup={g} members={members} />
                          ))}
                        </div>
                      )}
                    </div>
                  </Section>
                )}

                {rep.genes && urls[POOLED_FILE] && (
                  <Section
                    title="Every Gene, Every Study"
                    info="Every robust gene is a row, every dataset a column. The colour is which way that dataset alone saw the gene move. Two unbroken bands across every column means the datasets found the same thing independently."
                  >
                    <Panel>
                      {pooled.isPending && <Skeleton className="h-[480px] w-full" />}
                      {pooled.isError && (
                        <p className="text-sm text-danger">
                          Could not load the pooled gene table: {errorMessage(pooled.error)}
                        </p>
                      )}
                      {pooled.data && (
                        <AgreementWall
                          table={pooled.data}
                          onSelect={(symbol, geneId) => selectGene(symbol, geneId)}
                          themeKey={resolved}
                        />
                      )}
                      <p className="mt-3 text-[12px] text-ink-3">
                        Each column is one study, each row one gene, and the colours line up. The
                        number under a column is the share of robust genes that study saw move the
                        same way as the pool. When there are more genes than pixels a row is the
                        average of the genes in it.
                      </p>
                    </Panel>
                  </Section>
                )}

                {rep.genes && urls[POOLED_FILE] && (
                  <Section
                    title="The Pooled Volcano"
                    info="The same plot as on a single study, now for the pooled estimate. Darker, bigger points were found by more of the datasets on their own; hover one to see it in every dataset, click it to open the gene."
                  >
                    <Panel>
                      <div id="pooled-volcano" className="min-w-0">
                        <p
                          className="mb-4 inline-flex items-center gap-1.5 rounded-md px-3 py-1.5 text-[13px] font-bold text-white"
                          style={{ background: "#7b3294" }}
                        >
                          <MousePointerClick size={15} strokeWidth={2.25} aria-hidden />
                          Click any gene to learn more
                        </p>
                        {pooled.isPending && <PooledLoading />}
                        {pooled.data && (
                          <PooledVolcanoPanel
                            table={pooled.data}
                            alpha={rep.genes.alpha}
                            lfc0={rep.genes.lfc_threshold ?? 1}
                            term={term}
                            pin={asked}
                            selected={selected?.symbol ?? null}
                            onSelect={(symbol, geneId) => selectGene(symbol, geneId)}
                            themeKey={resolved}
                          />
                        )}
                      </div>
                    </Panel>
                  </Section>
                )}

                {rep.concordance && rep.concordance.members.length >= 2 && (
                  <Section
                    title="Do the Datasets Agree?"
                    info="One cell per pair of datasets: the correlation of every gene's test statistic between the two studies. Blue means they found the same biology; orange means the opposite, as when one study's case and control labels were swapped."
                  >
                    <Panel>
                      <ConcordanceHeatmap concordance={rep.concordance} />
                    </Panel>
                  </Section>
                )}

                {(pooledEnrichment?.top.length || rep.pathways?.terms.length) && (
                  <Section
                    title="Pathways, Pooled"
                    info="Gene set enrichment on the pooled statistic: which biological programmes move as a whole across every dataset. Click a set to mark its leading genes on the pooled volcano. The per-dataset view below shows the same sets in each study on its own."
                  >
                    <Panel>
                      {pooledEnrichment && pooledEnrichment.top.length > 0 && (
                        <div className="min-w-0">
                          <ColHead
                            label="Pathways across the pool"
                            detail={`${pooledEnrichment.n_sig_fdr} of ${pooledEnrichment.n_terms} sets at FDR < ${pooledEnrichment.fdr_threshold}`}
                          />
                          <EnrichmentDots
                            terms={pooledEnrichment.top}
                            selected={term?.term ?? null}
                            onSelect={setTerm}
                            caseLabel={rep.case_label}
                            controlLabel={rep.control_label}
                          />
                          <p className="mt-3 text-[12px] text-ink-3">
                            Each circle is a gene set. Further from the centre line is a stronger
                            shift, a bigger circle is a bigger set, and a darker circle is a surer
                            result. Click one to mark its leading genes on the pooled volcano.
                          </p>
                          <Details summary="As a table" className="mt-3">
                            <EnrichmentBars
                              terms={pooledEnrichment.top}
                              selected={term?.term ?? null}
                              onSelect={setTerm}
                            />
                          </Details>
                        </div>
                      )}
                      {pooledEnrichment && pooledEnrichment.top.length > 0 && (
                        <div className="mt-6 min-w-0 border-t border-line pt-5">
                          <ColHead label="How the pathways connect" />
                          <PathwayNetwork
                            terms={pooledEnrichment.top}
                            selected={term?.term ?? null}
                            onSelectTerm={setTerm}
                            onSelectGene={pick}
                            canPick={canPick}
                          />
                          <p className="mt-3 text-[12px] text-ink-3">
                            The strongest gene sets as hubs, joined to the genes that drive them.
                            Sets that share genes pull together. Click a gene to open it.
                          </p>
                        </div>
                      )}
                      {rep.pathways && rep.pathways.terms.length > 0 && (
                        <div className="mt-6 min-w-0 border-t border-line pt-5">
                          <Details
                            summary={`The same sets in each dataset: ${rep.pathways.n_consistent} of ${rep.pathways.n_terms} agree in every member`}
                          >
                            <div className="mt-2">
                              <PathwayMatrix pathways={rep.pathways} />
                              <p className="mt-3 text-[12px] text-ink-3">
                                One bubble per dataset and set: colour is the direction, size is the
                                confidence. A row of one colour is the same biology found
                                independently by every study.
                              </p>
                              <Details summary="As a table" className="mt-3">
                                <PathwaysTable pathways={rep.pathways} />
                              </Details>
                            </div>
                          </Details>
                        </div>
                      )}
                    </Panel>
                  </Section>
                )}

                {rep.genes && (rep.genes.top_up.length > 0 || rep.genes.top_down.length > 0) && (
                  <Section
                    title="Robust Genes"
                    info={`Ranked by pooled z among genes with |pooled log2FC| ≥ ${rep.genes.lfc_threshold}.`}
                  >
                    <Panel>
                      <div className="grid gap-6 lg:grid-cols-2 lg:gap-x-8">
                        <div className="min-w-0">
                          {perMember ? (
                            <>
                              <ColHead label={<Tag tone="case">Higher in case</Tag>} />
                              <ReplicationStrip
                                rows={rep.genes.top_up}
                                members={rep.genes.members}
                                alpha={rep.genes.alpha}
                                tone="case"
                                onSelect={pick}
                              />
                              <Details summary="As a table" className="mt-3">
                                <RobustGenes
                                  title="Higher in case"
                                  tone="case"
                                  rows={rep.genes.top_up}
                                />
                              </Details>
                            </>
                          ) : (
                            <RobustGenes
                              title="Higher in case"
                              tone="case"
                              rows={rep.genes.top_up}
                            />
                          )}
                        </div>
                        <div className="min-w-0 border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                          {perMember ? (
                            <>
                              <ColHead label={<Tag tone="control">Higher in control</Tag>} />
                              <ReplicationStrip
                                rows={rep.genes.top_down}
                                members={rep.genes.members}
                                alpha={rep.genes.alpha}
                                tone="control"
                                onSelect={pick}
                              />
                              <Details summary="As a table" className="mt-3">
                                <RobustGenes
                                  title="Higher in control"
                                  tone="control"
                                  rows={rep.genes.top_down}
                                />
                              </Details>
                            </>
                          ) : (
                            <RobustGenes
                              title="Higher in control"
                              tone="control"
                              rows={rep.genes.top_down}
                            />
                          )}
                        </div>
                      </div>
                      <p className="mt-4 text-[12px] text-ink-3">
                        {perMember
                          ? "Each row is a gene, each column a dataset. Reading across: the same change, seen independently in study after study."
                          : "This comparison was written before per-dataset estimates were stored with each gene, so the per-dataset view is unavailable; re-run the comparison to get it."}
                      </p>
                    </Panel>
                  </Section>
                )}

                <Section
                  title="The Ledger"
                  info="Which runs were pooled, how they were fitted, and what was held against them."
                >
                  <Panel>
                    <MemberLedger members={memberRows} />
                    {excluded.length > 0 && (
                      <div className="mt-4 border-t border-line pt-3">
                        <Details
                          summary={`${excluded.length} run${excluded.length === 1 ? "" : "s"} not pooled`}
                        >
                          <ul className="space-y-1">
                            {excluded.map((e) => (
                              <li key={e.label} className="flex flex-wrap items-center gap-2">
                                <span className="accession font-medium text-accent-ink">
                                  {e.gse ?? e.label}
                                </span>
                                <span className="tag inline-flex h-[22px] items-center rounded-md border border-danger/40 bg-danger-soft px-2 text-[12px] font-semibold text-danger">
                                  {e.reason.replaceAll("_", " ")}
                                </span>
                                <span className="text-ink-2">{e.detail}</span>
                              </li>
                            ))}
                          </ul>
                        </Details>
                      </div>
                    )}
                  </Panel>
                </Section>
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
                  {urls["comparison.md"] && (
                    <div className="mt-4 border-t border-line pt-3">
                      <MarkdownFile
                        url={urls["comparison.md"]}
                        summary="Read comparison.md inline"
                      />
                    </div>
                  )}
                </Panel>
              </Section>
            )}
          </>
        )}
        <Footer />
      </Page>
    </>
  );
}

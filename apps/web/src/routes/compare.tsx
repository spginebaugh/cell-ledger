import { Link } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { useEffect } from "react";
import { ConcordanceHeatmap } from "@/components/charts/heatmap";
import { GeneAcrossCard, RobustGenes } from "@/components/compare/genes";
import { MemberLedger } from "@/components/compare/ledger";
import { PathwaysTable } from "@/components/compare/pathways";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { Downloads, MarkdownFile } from "@/components/run/downloads";
import { StatusChip } from "@/components/ui/badge";
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
import { compareRoute } from "@/router";

export function ComparePage() {
  const { sessionId, name } = compareRoute.useParams();
  const q = useComparison(sessionId, name);
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
                        {fmtInt(rep.genes.n_genes_pooled)} genes pooled across{" "}
                        {memberRows.filter((m) => m.pooled).length} datasets.
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
                    info="Each gene's estimate per dataset (points, 95% interval) and the pooled estimate (diamond)."
                  >
                    <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                      {lookups.map((g) => (
                        <GeneAcrossCard key={g.query} lookup={g} members={members} />
                      ))}
                    </div>
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

                {((rep.concordance && rep.concordance.members.length >= 2) ||
                  (rep.pathways && rep.pathways.terms.length > 0)) && (
                  <Section
                    title="Agreement and Pathways"
                    info="Spearman correlation of Wald statistics over genes tested in both runs, and the hallmark sets that point the same way in every member."
                  >
                    <Panel>
                      <div className="grid gap-6 lg:grid-cols-2 lg:gap-x-8">
                        {rep.concordance && rep.concordance.members.length >= 2 && (
                          <div className="min-w-0">
                            <ColHead label="Do the datasets agree?" />
                            <ConcordanceHeatmap concordance={rep.concordance} />
                          </div>
                        )}
                        {rep.pathways && rep.pathways.terms.length > 0 && (
                          <div className="min-w-0 border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                            <ColHead
                              label="Pathways across datasets"
                              detail={`${rep.pathways.n_consistent} of ${rep.pathways.n_terms} sets agree in every member`}
                            />
                            <PathwaysTable pathways={rep.pathways} />
                          </div>
                        )}
                      </div>
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
                          <RobustGenes title="Higher in case" tone="case" rows={rep.genes.top_up} />
                        </div>
                        <div className="min-w-0 border-t border-line pt-4 lg:border-l lg:border-t-0 lg:pl-8 lg:pt-0">
                          <RobustGenes
                            title="Higher in control"
                            tone="control"
                            rows={rep.genes.top_down}
                          />
                        </div>
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

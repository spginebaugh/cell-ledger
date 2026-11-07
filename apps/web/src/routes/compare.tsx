import { Link } from "@tanstack/react-router";
import { Loader2 } from "lucide-react";
import { useEffect } from "react";
import { ConcordanceHeatmap } from "@/components/charts/heatmap";
import { GeneAcrossCard, RobustGenes } from "@/components/compare/genes";
import { MemberLedger } from "@/components/compare/ledger";
import { PathwaysTable } from "@/components/compare/pathways";
import { Page, TopBar } from "@/components/layout/top-bar";
import { Downloads, MarkdownFile } from "@/components/run/downloads";
import { Badge } from "@/components/ui/badge";
import { Card, Details, ErrorBox, Notice, Section, Skeleton } from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { fmtInt, statusLabel, statusTone } from "@/lib/format";
import { useComparison } from "@/lib/queries";
import { compareRoute } from "@/router";

export function ComparePage() {
  const { sessionId, name } = compareRoute.useParams();
  const q = useComparison(sessionId, name);
  useEffect(() => {
    document.title = `${name.replaceAll("_", " ")} · cell-ledger`;
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
  return (
    <>
      <TopBar sessionId={sessionId} />
      <Page>
        <nav className="text-[13px] text-ink-2">
          <Link to="/s/$sessionId" params={{ sessionId }} className="hover:underline">
            Session
          </Link>
          <span className="mx-1.5 text-ink-3">/</span>
          comparison
        </nav>
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
            <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
              <div className="max-w-[70ch]">
                <h1>{view.request.question}</h1>
                <p className="mt-2 text-ink-2">
                  <span className="text-case">{view.request.case_label}</span> vs{" "}
                  <span className="text-control">{view.request.control_label}</span> ·{" "}
                  {view.request.members.length} datasets ·{" "}
                  <span className="font-mono text-[14px]">{name}</span>
                </p>
              </div>
              <Badge tone={statusTone(view.status)} className="text-[13px]">
                {view.status === "running" && <Loader2 size={13} className="animate-spin" />}
                {statusLabel(view.status)}
              </Badge>
            </div>

            {view.status === "running" && (
              <Card className="mt-6 max-w-xl p-5">
                <h3>Pooling the runs</h3>
                <p className="mt-1 text-sm text-ink-2">
                  Random-effects meta-analysis per gene, concordance, pathways and pooled GSEA. This
                  takes a minute.
                </p>
              </Card>
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
                    <Notice tone="amber" title="Not enough datasets could be pooled for a verdict">
                      <ul>
                        {warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </Notice>
                  )}
                  {questions.length > 0 && (
                    <Notice tone="amber" title="Decide these before trusting the pool">
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
                      title={`${fmtInt(rep.genes.n_robust)} genes replicate across ${memberRows.filter((m) => m.pooled).length} pooled datasets`}
                    >
                      {fmtInt(rep.genes.n_robust_up)} higher in case,{" "}
                      {fmtInt(rep.genes.n_robust_down)} higher in control, out of{" "}
                      {fmtInt(rep.genes.n_genes_pooled)} genes pooled. A gene is robust when its
                      pooled padj &lt; {rep.genes.alpha}, its sign agrees in at least{" "}
                      {Math.round(rep.genes.sign_consistency * 100)}% of datasets and it is
                      significant in at least {Math.round(rep.genes.min_replication * 100)}%.
                    </Notice>
                  )}
                  {rep.status === "complete" && warnings.length > 0 && (
                    <Details
                      summary={`${warnings.length} warning${warnings.length === 1 ? "" : "s"}`}
                    >
                      <ul className="list-disc pl-5 text-sm text-ink-2">
                        {warnings.map((w) => (
                          <li key={w}>{w}</li>
                        ))}
                      </ul>
                    </Details>
                  )}
                </div>

                {lookups.length > 0 && (
                  <Section
                    title="The answer, across datasets"
                    description="Each gene's estimate per dataset (points, 95% interval) and the pooled estimate (diamond)."
                  >
                    <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                      {lookups.map((g) => (
                        <GeneAcrossCard key={g.query} lookup={g} members={members} />
                      ))}
                    </div>
                  </Section>
                )}

                <Section
                  title="The ledger"
                  description="Which runs were pooled, how they were fitted, and what was held against them."
                >
                  <MemberLedger members={memberRows} />
                  {excluded.length > 0 && (
                    <div className="mt-3">
                      <Details
                        summary={`${excluded.length} run${excluded.length === 1 ? "" : "s"} not pooled`}
                      >
                        <ul className="space-y-1 text-sm">
                          {excluded.map((e) => (
                            <li key={e.label}>
                              <span className="accession">{e.gse ?? e.label}</span>{" "}
                              <Badge tone="danger">{e.reason.replaceAll("_", " ")}</Badge>{" "}
                              <span className="text-ink-2">{e.detail}</span>
                            </li>
                          ))}
                        </ul>
                      </Details>
                    </div>
                  )}
                </Section>

                <div className="grid gap-6 lg:grid-cols-2">
                  {rep.concordance && rep.concordance.members.length >= 2 && (
                    <Section
                      title="Do the datasets agree?"
                      description="Spearman correlation of Wald statistics over genes tested in both runs."
                    >
                      <Card className="p-4">
                        <ConcordanceHeatmap concordance={rep.concordance} />
                      </Card>
                    </Section>
                  )}
                  {rep.pathways && rep.pathways.terms.length > 0 && (
                    <Section
                      title="Pathways across datasets"
                      description={`${rep.pathways.n_consistent} of ${rep.pathways.n_terms} sets point the same way in every member.`}
                    >
                      <PathwaysTable pathways={rep.pathways} />
                    </Section>
                  )}
                </div>

                {rep.genes && (rep.genes.top_up.length > 0 || rep.genes.top_down.length > 0) && (
                  <Section
                    title="Robust genes"
                    description={`Ranked by pooled z among genes with |pooled log2FC| ≥ ${rep.genes.lfc_threshold}.`}
                  >
                    <div className="grid gap-6 lg:grid-cols-2">
                      <RobustGenes title="Higher in case" rows={rep.genes.top_up} />
                      <RobustGenes title="Higher in control" rows={rep.genes.top_down} />
                    </div>
                  </Section>
                )}
              </>
            )}

            {Object.keys(urls).length > 0 && (
              <Section
                title="Files"
                description="Everything the comparison wrote. Links are valid for a day."
              >
                <Downloads urls={urls} />
                {urls["comparison.md"] && (
                  <div className="mt-4">
                    <MarkdownFile url={urls["comparison.md"]} summary="Read comparison.md inline" />
                  </div>
                )}
              </Section>
            )}
          </>
        )}
      </Page>
    </>
  );
}

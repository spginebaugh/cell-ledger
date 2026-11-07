import { useQueryClient } from "@tanstack/react-query";
import { useCallback, useEffect, useMemo, useState } from "react";
import type { DesignProposal, RunRequest, SessionInfo } from "@/api/generated/types.gen";
import { ManualAccessions } from "@/components/home/manual";
import { Page, TopBar } from "@/components/layout/top-bar";
import { ComparisonsSection } from "@/components/session/comparisons";
import { DatasetCard } from "@/components/session/dataset-card";
import { RunsList } from "@/components/session/runs-list";
import { Button } from "@/components/ui/button";
import { Empty, ErrorBox, Section, Skeleton } from "@/components/ui/card";
import { Textarea } from "@/components/ui/input";
import { errorMessage } from "@/lib/api";
import {
  keys,
  useAgentAvailable,
  useCollect,
  useComparisons,
  useDatasets,
  useRuns,
  useSession,
  useStartRun,
  useUpdateSession,
} from "@/lib/queries";
import { rememberSession } from "@/lib/storage";
import { guessGenes, readState, type UiState } from "@/lib/ui-state";
import { sessionRoute } from "@/router";

export function SessionPage() {
  const { sessionId } = sessionRoute.useParams();
  const session = useSession(sessionId);
  const datasets = useDatasets(sessionId, session.isSuccess);
  const runs = useRuns(sessionId, session.isSuccess);
  const comparisons = useComparisons(sessionId, session.isSuccess);
  const agent = useAgentAvailable();
  const qc = useQueryClient();
  const update = useUpdateSession(sessionId);
  const startRun = useStartRun(sessionId);
  const collect = useCollect(sessionId);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState("");
  const [startError, setStartError] = useState<Record<string, string | null>>({});
  const [startingGse, setStartingGse] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);

  useEffect(() => {
    if (session.isSuccess) rememberSession(sessionId);
  }, [session.isSuccess, sessionId]);
  useEffect(() => {
    document.title = session.data?.question
      ? `${session.data.question.slice(0, 60)} · cell-ledger`
      : "Session · cell-ledger";
  }, [session.data?.question]);

  const state: UiState = useMemo(() => readState(session.data?.state), [session.data?.state]);
  const question = session.data?.question ?? "";
  const genes = useMemo(
    () => state.genes ?? (question ? guessGenes(question) : []),
    [state.genes, question],
  );

  // Context discovery settled that the design step should not have to rediscover.
  const designContext = useMemo(
    () =>
      [
        state.discovery?.interpretation &&
          `The question as a two-group comparison: ${state.discovery.interpretation}`,
        state.answers && `Clarifications from the user: ${state.answers}`,
      ]
        .filter(Boolean)
        .join("\n"),
    [state.discovery?.interpretation, state.answers],
  );

  // Patches are computed from the latest cached state at call time, not from a closure, so two
  // cards saving at once do not overwrite each other. `mutate` is stable; the mutation result
  // object is not, and depending on it made every consumer callback change each render.
  const { mutate } = update;
  const saveState = useCallback(
    (patch: (current: UiState) => Partial<UiState>) => {
      const current = readState(qc.getQueryData<SessionInfo>(keys.session(sessionId))?.state);
      mutate({ state: { ...current, ...patch(current) } });
    },
    [qc, sessionId, mutate],
  );

  const onProposal = useCallback(
    (gse: string, p: DesignProposal | null) =>
      saveState((current) => {
        const proposals = { ...(current.proposals ?? {}) };
        if (p) proposals[gse] = p;
        else delete proposals[gse];
        return { proposals };
      }),
    [saveState],
  );

  const onStartRun = async (design: RunRequest) => {
    const gse = design.samplesheet.gse;
    setStartingGse(gse);
    setStartError((e) => ({ ...e, [gse]: null }));
    try {
      await startRun.mutateAsync(design);
      const el = document.getElementById("runs");
      el?.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (err) {
      setStartError((e) => ({ ...e, [gse]: errorMessage(err) }));
    } finally {
      setStartingGse(null);
    }
  };

  const runsByGse = useMemo(() => new Set((runs.data ?? []).map((r) => r.gse)), [runs.data]);

  return (
    <>
      <TopBar sessionId={sessionId} />
      <Page>
        {session.isPending && (
          <div className="space-y-4">
            <Skeleton className="h-10 w-2/3" />
            <Skeleton className="h-32" />
          </div>
        )}
        {session.isError && (
          <ErrorBox title="This session could not be opened">
            {errorMessage(session.error)}. Sessions expire a day after they were created.
          </ErrorBox>
        )}
        {session.data && (
          <>
            <div className="flex flex-wrap items-start justify-between gap-4">
              <div className="min-w-0 max-w-[70ch] flex-1">
                <p className="text-[13px] text-ink-2">The question</p>
                {editing ? (
                  <div className="mt-1">
                    <Textarea
                      rows={2}
                      value={draft}
                      onChange={(e) => setDraft(e.target.value)}
                      className="text-[17px]"
                      aria-label="Edit the question"
                    />
                    <div className="mt-2 flex gap-2">
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => {
                          update.mutate({ question: draft.trim() });
                          setEditing(false);
                        }}
                        disabled={!draft.trim()}
                      >
                        Save
                      </Button>
                      <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
                        Cancel
                      </Button>
                    </div>
                  </div>
                ) : (
                  <h1 className="mt-1">
                    {question || <span className="text-ink-3">No question recorded</span>}
                  </h1>
                )}
              </div>
              {!editing && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setDraft(question);
                    setEditing(true);
                  }}
                >
                  Edit
                </Button>
              )}
            </div>
            {state.discovery?.interpretation && (
              <p className="mt-2 max-w-[70ch] text-ink-2">
                Read as: {state.discovery.interpretation}
              </p>
            )}

            <Section
              title="Datasets"
              description="Each series is downloaded from NCBI and checked: human, bulk RNA-seq, raw counts present. Ready ones can be designed and run."
              actions={
                <Button size="sm" onClick={() => setAdding((a) => !a)}>
                  {adding ? "Close" : "Add datasets"}
                </Button>
              }
            >
              {adding && (
                <div className="mb-4">
                  <ManualAccessions
                    genes={genes}
                    onGenesChange={(g) => saveState(() => ({ genes: g }))}
                    onCollect={(gses) => {
                      collect.mutate(gses, { onSuccess: () => setAdding(false) });
                    }}
                    collecting={collect.isPending}
                  />
                  {collect.isError && (
                    <div className="mt-2">
                      <ErrorBox title="Could not start the downloads">
                        {errorMessage(collect.error)}
                      </ErrorBox>
                    </div>
                  )}
                </div>
              )}
              {datasets.isPending && <Skeleton className="h-24" />}
              {datasets.data && datasets.data.length === 0 && !adding && (
                <Empty title="No datasets in this session">
                  Add accessions to download their counts and sample records.
                </Empty>
              )}
              <div className="space-y-3">
                {(datasets.data ?? []).map((d) => (
                  <DatasetCard
                    key={d.gse}
                    sessionId={sessionId}
                    dataset={d}
                    question={question}
                    context={designContext}
                    agentAvailable={Boolean(agent.data)}
                    defaultGenes={genes}
                    proposal={state.proposals?.[d.gse]}
                    onProposal={onProposal}
                    onStartRun={onStartRun}
                    starting={startingGse === d.gse}
                    startError={startError[d.gse] ?? null}
                    hasRun={runsByGse.has(d.gse)}
                  />
                ))}
              </div>
            </Section>

            <Section
              id="runs"
              title="Runs"
              description="One row per contrast. A run polls the pipeline while it works and links to its result when done."
            >
              {runs.isPending ? (
                <Skeleton className="h-20" />
              ) : (
                <RunsList sessionId={sessionId} runs={runs.data ?? []} />
              )}
            </Section>

            <Section
              title="Across datasets"
              description="Pool finished runs that answer the same question and see what replicates."
            >
              {comparisons.isPending ? (
                <Skeleton className="h-20" />
              ) : (
                <ComparisonsSection
                  sessionId={sessionId}
                  comparisons={comparisons.data ?? []}
                  runs={runs.data ?? []}
                  question={question}
                  genes={genes}
                />
              )}
            </Section>
          </>
        )}
      </Page>
    </>
  );
}

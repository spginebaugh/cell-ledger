import { useEffect, useMemo, useState } from "react";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { ComparisonsSection } from "@/components/session/comparisons";
import { DatasetRow, deriveStage, PipelineStepper } from "@/components/session/pipeline-view";
import { RunsList } from "@/components/session/runs-list";
import { Empty, ErrorBox, Pill, Section, Skeleton } from "@/components/ui/card";
import { errorMessage } from "@/lib/api";
import { useComparisons, useDatasets, useRuns, useSession } from "@/lib/queries";
import { rememberSession } from "@/lib/storage";
import { readState, type UiState } from "@/lib/ui-state";
import { sessionRoute } from "@/router";

/** The session after the last click: a progress view that fills in as the pipeline runs. */
export function SessionPage() {
  const { sessionId } = sessionRoute.useParams();
  const session = useSession(sessionId);
  // Poll all three lists while the pipeline is in flight; the stage below is read off them,
  // and once it says done the polling stops (the initial fetch happens regardless).
  const [poll, setPoll] = useState(true);
  const datasets = useDatasets(sessionId, session.isSuccess, poll);
  const runs = useRuns(sessionId, session.isSuccess, poll);
  const comparisons = useComparisons(sessionId, session.isSuccess, poll);

  useEffect(() => {
    if (session.isSuccess) rememberSession(sessionId);
  }, [session.isSuccess, sessionId]);
  useEffect(() => {
    document.title = session.data?.question
      ? `${session.data.question.slice(0, 60)} · cell ledger`
      : "Session · cell ledger";
  }, [session.data?.question]);

  const state: UiState = useMemo(() => readState(session.data?.state), [session.data?.state]);
  const question = session.data?.question ?? "";
  const ds = datasets.data ?? [];
  const rs = runs.data ?? [];
  const cs = comparisons.data ?? [];
  const { stage, settled, completeDatasets } = useMemo(() => deriveStage(ds, rs, cs), [ds, rs, cs]);
  const runByGse = useMemo(() => new Map(rs.map((r) => [r.gse, r])), [rs]);
  const loaded = datasets.isSuccess && runs.isSuccess && comparisons.isSuccess;
  useEffect(() => {
    setPoll(!(loaded && settled));
  }, [loaded, settled]);

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
            <div className="flex items-center justify-between gap-2 text-[13px]">
              <span className="font-semibold text-ink-2">The question</span>
              {loaded && ds.length > 0 && <PipelineStepper stage={stage} />}
            </div>
            <h1 className="mt-3 w-full">
              {question || <span className="text-ink-3">No question recorded</span>}
            </h1>
            {(state.discovery?.interpretation || state.answers) && (
              <div className="mt-5 grid justify-items-start gap-2">
                {state.discovery?.interpretation && (
                  <Pill label="Read as">{state.discovery.interpretation}</Pill>
                )}
                {state.answers && <Pill label="You added">{state.answers}</Pill>}
              </div>
            )}

            <Section
              title="Individual Datasets"
              info="Each series is downloaded from NCBI and checked, then the specialist labels its samples and chooses the one contrast that answers the question. Runnable contrasts start at once; the rest are set aside with the reason."
            >
              {datasets.isPending && <Skeleton className="h-24" />}
              {datasets.data && datasets.data.length === 0 && (
                <Empty title="No datasets in this session">
                  Start from the home page: ask a question and pick the datasets to download.
                </Empty>
              )}
              <div className="space-y-3">
                {ds.map((d) => (
                  <DatasetRow
                    key={d.gse}
                    sessionId={sessionId}
                    dataset={d}
                    run={runByGse.get(d.gse)}
                  />
                ))}
              </div>
            </Section>

            <Section
              title="Across Datasets"
              info="When every run is done, the complete ones are pooled to see what replicates."
            >
              {comparisons.isPending ? (
                <Skeleton className="h-20" />
              ) : (
                <ComparisonsSection
                  sessionId={sessionId}
                  comparisons={cs}
                  completeRuns={completeDatasets}
                  settled={settled}
                />
              )}
            </Section>

            <Section
              id="runs"
              title="Runs"
              info="One per dataset with a runnable contrast. A run polls the pipeline while it works and links to its result when done."
            >
              {runs.isPending ? (
                <Skeleton className="h-20" />
              ) : (
                <RunsList sessionId={sessionId} runs={rs} />
              )}
            </Section>
          </>
        )}
        <Footer />
      </Page>
    </>
  );
}

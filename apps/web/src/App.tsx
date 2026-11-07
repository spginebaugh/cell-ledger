import { useEffect, useState } from "react";
import type { RunSnapshot } from "./api/generated";
import { useHealth } from "./api/health";
import { GroupQuestion, SampleEvidence } from "./RunDetails";
import { SavedRuns } from "./SavedRuns";

type Dataset = { gse: string; title: string; status: string; reasons: string[]; samples?: number };

export function App() {
  const health = useHealth();
  const [topic, setTopic] = useState("");
  const [caseLabel, setCaseLabel] = useState("");
  const [controlLabel, setControlLabel] = useState("");
  const [runId, setRunId] = useState(() => localStorage.getItem("cell-ledger-run") ?? "");
  const [run, setRun] = useState<RunSnapshot | null>(null);
  const [error, setError] = useState("");
  const [submitting, setSubmitting] = useState(false);

  useEffect(() => {
    if (!runId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const response = await fetch(`/api/runs/${runId}`);
        if (!response.ok)
          throw new Error(
            response.status === 503
              ? "Saved run storage is temporarily unavailable. Retrying…"
              : "Could not load this run. Check that it was saved successfully.",
          );
        const next: RunSnapshot = await response.json();
        if (stopped) return;
        setRun(next);
        setError("");
        if (next.status === "running") timer = setTimeout(poll, 1200);
      } catch (cause) {
        if (!stopped) {
          setError(cause instanceof Error ? cause.message : "Could not load run");
          timer = setTimeout(poll, 4000);
        }
      }
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [runId]);

  const startRun = async (event: React.FormEvent) => {
    event.preventDefault();
    setSubmitting(true);
    setError("");
    try {
      const response = await fetch("/api/runs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          topic,
          case: caseLabel || null,
          control: controlLabel || null,
          ask_user: true,
        }),
      });
      if (!response.ok) {
        const detail = await response.json();
        throw new Error(
          typeof detail.detail === "string" ? detail.detail : "Check your search inputs.",
        );
      }
      const created: { id: string } = await response.json();
      localStorage.setItem("cell-ledger-run", created.id);
      setRun(null);
      setRunId(created.id);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not start run");
    } finally {
      setSubmitting(false);
    }
  };

  const datasets = (run?.manifest.datasets ?? []) as Dataset[];
  const active = submitting || Boolean(!error && runId && (!run || run.status === "running"));
  return (
    <main>
      <header>
        <span className="eyebrow">PUBLIC DATA · TRACEABLE DECISIONS</span>
        <h1>cell-ledger</h1>
        <p className="intro">From a research question to a study you can work with.</p>
        <p>
          Find human bulk RNA-seq studies in GEO. Inspect sample labels, check raw counts, and
          download an independent analysis bundle for each study.
        </p>
      </header>
      <form onSubmit={startRun}>
        <label htmlFor="topic">What are you investigating?</label>
        <textarea
          id="topic"
          required
          minLength={3}
          maxLength={2000}
          value={topic}
          onChange={(event) => setTopic(event.target.value)}
          placeholder="IFN-gamma stimulated human macrophages"
        />
        <details>
          <summary>Specify case and control labels</summary>
          <p>
            Use exact condition or treatment values from the source metadata. Unresolved groups stay
            unknown.
          </p>
          <div className="fields">
            <label>
              Case
              <input value={caseLabel} onChange={(event) => setCaseLabel(event.target.value)} />
            </label>
            <label>
              Control
              <input
                value={controlLabel}
                onChange={(event) => setControlLabel(event.target.value)}
              />
            </label>
          </div>
        </details>
        <button type="submit" disabled={active}>
          {active ? "Preparing studies…" : "Find studies"}
        </button>
        <small>Human bulk RNA-seq only · Up to 3 studies · No analysis runs automatically</small>
      </form>
      <SavedRuns
        selectedId={runId}
        disabled={active}
        refreshKey={run ? `${run.id}:${run.status}` : ""}
        onOpen={(id) => {
          if (id === runId) return;
          localStorage.setItem("cell-ledger-run", id);
          setRun(null);
          setError("");
          setRunId(id);
        }}
      />
      {error && (
        <p role="alert" className="notice">
          {error}
        </p>
      )}
      {run && (
        <section aria-live="polite">
          <div className="section-heading">
            <h2>Your run</h2>
            <span className="badge">{run.status.replaceAll("_", " ")}</span>
          </div>
          {run.pending_question && (
            <GroupQuestion
              key={`${run.id}-${String(run.pending_question.gse)}`}
              runId={run.id}
              question={run.pending_question as { gse: string; options: string[] }}
            />
          )}
          <div className="workspace">
            <aside>
              <h3>Activity</h3>
              <ol>
                {run.events.map((event) => (
                  <li key={String(event.id)}>{String(event.message)}</li>
                ))}
              </ol>
              {run.events.length === 0 && (
                <p>
                  {run.status === "running"
                    ? "Preparing your request…"
                    : "No retrieval steps were needed."}
                </p>
              )}
            </aside>
            <div>
              <h3>Studies considered</h3>
              {datasets.map((dataset) => (
                <article key={`${run.id}:${dataset.gse}`}>
                  <div className="section-heading">
                    <a
                      href={`https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=${dataset.gse}`}
                      target="_blank"
                      rel="noreferrer"
                    >
                      {dataset.gse}
                    </a>
                    <span className="badge">{dataset.status.replaceAll("_", " ")}</span>
                  </div>
                  <h4>{dataset.title}</h4>
                  {dataset.samples !== undefined && <p>{dataset.samples} samples exported</p>}
                  <ul>
                    {dataset.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                  {dataset.samples !== undefined && (
                    <SampleEvidence runId={run.id} gse={dataset.gse} />
                  )}
                </article>
              ))}
              {datasets.length === 0 && run.status !== "running" && (
                <p>No study bundles were prepared. Review the notes below.</p>
              )}
            </div>
          </div>
          {run.questions.trim() && (
            <div className="notice">
              <h3>Questions and limits</h3>
              <pre>{run.questions}</pre>
            </div>
          )}
          {run.status !== "running" && (
            <a className="download" href={`/api/runs/${run.id}/bundle`}>
              Download run bundle
            </a>
          )}
        </section>
      )}
      <footer>
        <p data-testid="api-status">
          {health.isPending && "Checking API…"}
          {health.isError && `API unreachable: ${health.error.message}`}
          {health.isSuccess &&
            `API ${health.data.status} (api ${health.data.api_version}, core ${health.data.core_version})`}
        </p>
        <p>Every study stays separate. A prepared bundle is not a biological result.</p>
      </footer>
    </main>
  );
}

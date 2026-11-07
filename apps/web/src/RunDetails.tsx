import { useState } from "react";

export function GroupQuestion({
  runId,
  question,
}: {
  runId: string;
  question: { gse: string; options: string[] };
}) {
  const [caseLabel, setCaseLabel] = useState("");
  const [controlLabel, setControlLabel] = useState("");
  const [error, setError] = useState("");
  const [sent, setSent] = useState(false);
  const answer = async (skip: boolean) => {
    setSent(true);
    setError("");
    try {
      const response = await fetch(`/api/runs/${runId}/answer`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ case: caseLabel, control: controlLabel, skip }),
      });
      if (!response.ok)
        throw new Error(
          "Could not accept that answer. Choose distinct labels or leave unresolved.",
        );
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Could not submit answer");
      setSent(false);
    }
  };
  return (
    <div className="notice">
      <h3>{question.gse}: which groups should be compared?</h3>
      <p>
        These labels come directly from the source metadata. Leave this unresolved if the study
        cannot support your question.
      </p>
      <div className="fields">
        <label>
          Choose case
          <select value={caseLabel} onChange={(e) => setCaseLabel(e.target.value)}>
            <option value="">Select a label</option>
            {question.options.map((option) => (
              <option key={option}>{option}</option>
            ))}
          </select>
        </label>
        <label>
          Choose control
          <select value={controlLabel} onChange={(e) => setControlLabel(e.target.value)}>
            <option value="">Select a label</option>
            {question.options.map((option) => (
              <option key={option}>{option}</option>
            ))}
          </select>
        </label>
      </div>
      <button
        type="button"
        disabled={sent || !caseLabel || !controlLabel || caseLabel === controlLabel}
        onClick={() => void answer(false)}
      >
        Use these groups
      </button>{" "}
      <button type="button" disabled={sent} onClick={() => void answer(true)}>
        Leave unresolved
      </button>
      {sent && <p>Continuing your run…</p>}
      {error && <p role="alert">{error}</p>}
    </div>
  );
}

export function SampleEvidence({ runId, gse }: { runId: string; gse: string }) {
  const [rows, setRows] = useState<Record<string, string>[] | null>(null);
  const [error, setError] = useState("");
  const load = async () => {
    if (rows) return;
    try {
      const response = await fetch(`/api/runs/${runId}/samples/${gse}`);
      if (!response.ok) throw new Error("Sample evidence is not available yet.");
      setRows(await response.json());
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Unable to load samples");
    }
  };
  return (
    <details
      onToggle={(event) => {
        if (event.currentTarget.open) void load();
      }}
    >
      <summary>Inspect samples and evidence</summary>
      {error && <p role="alert">{error}</p>}
      {!rows && !error && <p>Loading sample evidence…</p>}
      {rows && (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Sample</th>
                <th>Group</th>
                <th>Condition</th>
                <th>Verbatim evidence</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const evidence = JSON.parse(row.evidence) as Record<string, { evidence: string }>;
                return (
                  <tr key={row.gsm}>
                    <td>{row.gsm}</td>
                    <td>{row.group}</td>
                    <td>{row.condition || "Unknown"}</td>
                    <td>
                      {Array.from(
                        new Set(Object.values(evidence).map((label) => label.evidence)),
                      ).join("; ")}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </details>
  );
}

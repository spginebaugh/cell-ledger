import { Check, X } from "lucide-react";
import type { ReactNode } from "react";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { Badge } from "@/components/ui/badge";
import { Details, Panel, Section } from "@/components/ui/card";
import { Table, Td, Th } from "@/components/ui/table";
import {
  type CaseRun,
  EVAL_RESULTS,
  type EvalCase,
  type Ratio,
  type SystemId,
} from "@/lib/eval-results";
import { cn } from "@/lib/utils";

const { meta, summary, cases } = EVAL_RESULTS;

/** The two systems, in display order: the specialist first, the baseline as context. */
const SYSTEMS: { id: SystemId; name: string; short: string; fill: string }[] = [
  { id: "specialist", name: "Cell Ledger", short: "Cell Ledger", fill: "bg-case" },
  { id: "baseline", name: "Claude + web search", short: "Claude + web", fill: "bg-muted" },
];

const ACTION: Record<string, string> = {
  proceed: "found datasets",
  ask: "asked a question",
  decline: "declined",
  no_results: "reported nothing found",
  error: "errored",
};

function pct(r: Ratio): string {
  return r.value === null ? "n/a" : `${Math.round(r.value * 100)}%`;
}

function frac(r: Ratio): string {
  return r.d ? `${r.n} of ${r.d}` : "";
}

export function EvalsPage() {
  const runDate = new Date(meta.startedAt).toLocaleDateString(undefined, {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
  return (
    <>
      <TopBar />
      <Page>
        <header className="max-w-[75ch]">
          <p className="text-[13px] font-semibold text-ink-2">Evals</p>
          <h1 className="mt-1">Does the specialist find the right data?</h1>
          <p className="mt-3 text-ink-2">
            Cell Ledger and the same Claude model with web search and web fetch were given the same{" "}
            {meta.cases} dataset-discovery questions. Each question has an answer key: the GEO
            series that can answer it and, inside each, the samples that belong in each arm.
          </p>
          <p className="mt-2 text-[13px] text-ink-3">
            Run {runDate} · <span className="accession">{meta.model}</span> ({meta.effort} effort) ·{" "}
            {meta.cases} cases · one run each · result sealed in{" "}
            <span className="accession">evals/results/final-2026-11-07</span>
          </p>
          <Legend className="mt-4" />
        </header>

        <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <MeterCard
            title="Cases passed"
            hint="Right first move, nothing wrong recommended, the right datasets found"
            pick={(s) => summary[s].passed}
          />
          <MeterCard
            title="Correct datasets found"
            hint="Share of the answer key's series each system returned"
            pick={(s) => summary[s].recall}
          />
          <MeterCard
            title="Recommendations that were right"
            hint="Of the series it recommended that have a verdict"
            pick={(s) => summary[s].precision}
          />
          <MeterCard
            title="Samples in the right arm"
            hint="Of the answer key's samples, in the series each system found"
            pick={(s) => summary[s].sampleRecall}
          />
        </div>

        <Panel className="mt-4 grid gasm:grid-cols-2 lg:grid-cols-4">
          <PairStat
            label="Series with both arms exactly right"
            values={(s) => `${pct(summary[s].subsetsExact)} (${frac(summary[s].subsetsExact)})`}
          />
          <PairStat
            label="Recommended series that fail GEO eligibility"
            values={(s) => String(summary[s].ineligible)}
          />
          <PairStat label="Time per run" values={(s) => `${summary[s].secondsPerRun} s`} />
          <PairStat
            label="Input tokens per run"
            values={(s) => summary[s].inputTokensPerRun.toLocaleString()}
          />
        </Panel>

        <Section
          title="Case by case"
          info="What each system did on its first turn, then how its final answer scored against the answer key."
        >
          <Panel>
            <Table>
              <thead>
                <tr>
                  <Th>Question</Th>
                  <Th>Expected</Th>
                  {SYSTEMS.map((s) => (
                    <Th key={s.id}>{s.name}</Th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {cases.map((c) => (
                  <tr key={c.id}>
                    <Td className="min-w-[260px] max-w-[420px] py-3">
                      <div className="font-medium">{c.title}</div>
                      <div className="mt-0.5 text-[13px] text-ink-2">{c.prompt}</div>
                      <div className="mt-1 text-[12px] text-ink-3">{c.probes}</div>
                    </Td>
                    <Td className="whitespace-nowrap py-3 text-[13px] text-ink-2">
                      {ACTION[c.expected] ?? c.expected}
                      {c.alsoAcceptable.length > 0 && (
                        <div className="text-ink-3">
                          or {c.alsoAcceptable.map((a) => ACTION[a] ?? a).join(", ")}
                        </div>
                      )}
                    </Td>
                    {SYSTEMS.map((s) => (
                      <Td key={s.id} className="min-w-[200px] py-3">
                        <Outcome run={c[s.id]} />
                      </Td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </Table>
          </Panel>
        </Section>

        <Section
          title="Every metric"
          info="Pooled over all cases. Recall is not scored on ask-only cases, which end at the question."
        >
          <MetricsTable />
        </Section>

        <Section
          title="The questions each system asked"
          info="Verbatim, from the first turn. Asking is scored yes or no against the expected action; whether a question was worth asking is for you to judge."
        >
          <div className="grid gap-2">
            {cases
              .filter((c) => c.specialist.questions.length || c.baseline.questions.length)
              .map((c) => (
                <QuestionsFor key={c.id} c={c} />
              ))}
          </div>
        </Section>

        <Section title="How it was run">
          <div className="grid max-w-[75ch] gap-3 text-[15px] text-ink-2">
            <p>
              <strong className="text-ink">Cell Ledger</strong> searches GEO through NCBI's
              E-utilities, reads each candidate series' sample records, and chooses samples with
              rules over the verbatim GEO fields; code turns the rules into exact sample lists and
              checks them against NCBI's count tables.
            </p>
            <p>
              <strong className="text-ink">The baseline</strong> is the same model and effort with
              Anthropic's web search and web fetch tools, the same question, the same requirements
              in plain words (human bulk RNA-seq with NCBI counts, both arms in one series, at least
              three samples per arm, at most ten datasets) and the same answer format, naming its
              samples directly. Nothing else.
            </p>
            <p>
              Every recommended accession is checked against GEO by code: absent is fabricated,
              present but not human bulk RNA-seq with counts is ineligible. When a system asks a
              question on a case that should proceed, a scripted reply restating the question's
              constraints is sent, so it still gets to answer; the unnecessary question still counts
              against its first move.
            </p>
          </div>
        </Section>
        <Footer />
      </Page>
    </>
  );
}

function Legend({ className }: { className?: string }) {
  return (
    <div className={cn("flex flex-wrap gap-4 text-[13px] text-ink-2", className)}>
      {SYSTEMS.map((s) => (
        <span key={s.id} className="inline-flex items-center gap-1.5">
          <span className={cn("inline-block h-2.5 w-2.5 rounded-sm", s.fill)} aria-hidden />
          {s.name}
        </span>
      ))}
    </div>
  );
}

function MeterCard({
  title,
  hint,
  pick,
}: {
  title: string;
  hint: string;
  pick: (s: SystemId) => Ratio;
}) {
  return (
    <Panel className="">
      <div className="text-[13px] font-medium text-ink">{title}</div>
      <div className="mt-0.5 min-h-[2.5em] text-[12px] text-ink-3">{hint}</div>
      <div className="mt-3 grid gap-2.5">
        {SYSTEMS.map((s) => {
          const r = pick(s.id);
          const width = r.value === null ? 0 : Math.max(0, Math.min(1, r.value)) * 100;
          return (
            <div key={s.id} title={`${s.name}: ${pct(r)} (${frac(r)})`}>
              <div className="flex items-baseline justify-between gap-2 text-[12px]">
                <span className="text-ink-2">{s.short}</span>
                <span className="num">
                  <span
                    className={cn(
                      "text-[1.05rem] font-medium",
                      s.id === "specialist" ? "text-ink" : "text-ink-2",
                    )}
                  >
                    {pct(r)}
                  </span>{" "}
                  <span className="text-ink-3">{frac(r)}</span>
                </span>
              </div>
              <div
                className="mt-1 h-2 w-full rounded-full bg-surface-2"
                role="img"
                aria-label={`${s.name} ${pct(r)}`}
              >
                <div className={cn("h-2 rounded-full", s.fill)} style={{ width: `${width}%` }} />
              </div>
            </div>
          );
        })}
      </div>
    </Panel>
  );
}

function PairStat({ label, values }: { label: string; values: (s: SystemId) => string }) {
  return (
    <div>
      <div className="text-[13px] text-ink-2">{label}</div>
      <dl className="mt-1 grid grid-cols-[auto_1fr] gap-x-3 text-[13px]">
        {SYSTEMS.map((s) => (
          <div key={s.id} className="contents">
            <dt className="text-ink-3">{s.short}</dt>
            <dd className={cn("num m-0", s.id === "specialist" ? "font-medium" : "text-ink-2")}>
              {values(s.id)}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

function Outcome({ run }: { run: CaseRun }) {
  const bits: ReactNode[] = [];
  bits.push(
    <span key="a" className={run.actionCorrect ? "text-ink-2" : "text-danger"}>
      {ACTION[run.firstAction] ?? run.firstAction}
      {run.actionCorrect ? "" : " (not expected)"}
    </span>,
  );
  if (run.recall.d) bits.push(<span key="r">datasets {frac(run.recall)}</span>);
  if (run.subsetsExact.d)
    bits.push(<span key="x">arms exactly right {frac(run.subsetsExact)}</span>);
  if (run.sampleRecall.d && !run.subsetsExact.n)
    bits.push(<span key="s">samples named {pct(run.sampleRecall)}</span>);
  if (run.wrong)
    bits.push(
      <span key="w" className="text-danger">
        {run.wrong} wrong
      </span>,
    );
  return (
    <div>
      {run.passed ? (
        <Badge tone="ok">
          <Check size={12} aria-hidden /> Pass
        </Badge>
      ) : (
        <Badge tone="danger">
          <X size={12} aria-hidden /> Fail
        </Badge>
      )}
      <div className="mt-1 grid gap-0.5 text-[12px] text-ink-3">{bits}</div>
    </div>
  );
}

function MetricsTable() {
  const rows: { label: string; value: (s: SystemId) => string }[] = [
    { label: "Cases passed", value: (s) => withFrac(summary[s].passed) },
    { label: "Right first move", value: (s) => withFrac(summary[s].actionAccuracy) },
    { label: "Asked when it should", value: (s) => withFrac(summary[s].shouldAsk) },
    { label: "Asked when it should not", value: (s) => withFrac(summary[s].falseAsk) },
    { label: "Second turn correct", value: (s) => withFrac(summary[s].secondTurn) },
    { label: "Correct datasets found (recall)", value: (s) => withFrac(summary[s].recall) },
    {
      label: "Recommendations that were right (precision)",
      value: (s) => withFrac(summary[s].precision),
    },
    { label: "Samples in the right arm (recall)", value: (s) => withFrac(summary[s].sampleRecall) },
    {
      label: "Samples named that were right (precision)",
      value: (s) => withFrac(summary[s].samplePrecision),
    },
    {
      label: "Series with both arms exactly right",
      value: (s) => withFrac(summary[s].subsetsExact),
    },
    {
      label: "Recommended series that fail GEO eligibility",
      value: (s) => String(summary[s].ineligible),
    },
    { label: "Fabricated accessions", value: (s) => String(summary[s].fabricated) },
    { label: "GEO searches per run", value: (s) => String(summary[s].geoQueriesPerRun) },
    { label: "Web searches per run", value: (s) => String(summary[s].webSearchesPerRun) },
    { label: "Web fetches per run", value: (s) => String(summary[s].webFetchesPerRun) },
    { label: "Input tokens per run", value: (s) => summary[s].inputTokensPerRun.toLocaleString() },
    { label: "Seconds per run", value: (s) => String(summary[s].secondsPerRun) },
  ];
  return (
    <Panel>
      <Table>
        <thead>
          <tr>
            <Th>Metric</Th>
            {SYSTEMS.map((s) => (
              <Th key={s.id} className="text-right">
                {s.name}
              </Th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label}>
              <Td>{r.label}</Td>
              {SYSTEMS.map((s) => (
                <Td
                  key={s.id}
                  className={cn(
                    "num text-right",
                    s.id === "specialist" ? "font-medium" : "text-ink-2",
                  )}
                >
                  {r.value(s.id)}
                </Td>
              ))}
            </tr>
          ))}
        </tbody>
      </Table>
    </Panel>
  );
}

function withFrac(r: Ratio): string {
  return r.d ? `${pct(r)} (${r.n}/${r.d})` : "n/a";
}

function QuestionsFor({ c }: { c: EvalCase }) {
  const counts = SYSTEMS.map((s) => `${s.short} ${c[s.id].questions.length}`).join(" · ");
  return (
    <Details
      summary={
        <span className="flex flex-wrap items-baseline gap-x-3">
          <span className="text-ink">{c.title}</span>
          <span className="text-[12px] font-normal text-ink-3">
            expected: {ACTION[c.expected] ?? c.expected} · questions: {counts}
          </span>
        </span>
      }
    >
      <div className="grid gap-4 md:grid-cols-2">
        {SYSTEMS.map((s) => (
          <div key={s.id}>
            <div className="text-[13px] font-medium">{s.name}</div>
            {c[s.id].questions.length ? (
              <ul className="mt-1 list-disc pl-5 text-[14px] text-ink-2">
                {c[s.id].questions.map((q) => (
                  <li key={q} className="mt-1">
                    {q}
                  </li>
                ))}
              </ul>
            ) : (
              <p className="mt-1 text-[14px] text-ink-3">Asked nothing.</p>
            )}
          </div>
        ))}
      </div>
    </Details>
  );
}

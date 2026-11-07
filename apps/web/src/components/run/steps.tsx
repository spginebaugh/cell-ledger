import { Check, CircleDashed, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import type { RunProgress, StepRecord } from "@/api/generated/types.gen";
import { elapsedSince, fmtSeconds, PIPELINE_STEPS, stepLabel } from "@/lib/format";
import { cn } from "@/lib/utils";

/** Live stepper for a running contrast, from RunProgress; falls back to the queued state. */
export function LiveStepper({
  progress,
  startedAt,
  compact = false,
}: {
  progress: RunProgress | null | undefined;
  startedAt: string;
  compact?: boolean;
}) {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 1000);
    return () => clearInterval(id);
  }, []);
  const steps = progress?.steps ?? [];
  const done = new Map(steps.filter((s) => s.status === "done").map((s) => [s.name, s]));
  const running = steps.find((s) => s.status === "running");
  const known = new Set(PIPELINE_STEPS);
  const extra = steps.map((s) => s.name).filter((n) => !known.has(n));
  const names = [...PIPELINE_STEPS, ...extra];
  if (!progress || progress.queued) {
    return (
      <div className={cn("flex items-center gap-2 text-sm text-ink-2", compact && "text-[13px]")}>
        <Loader2 size={15} className="animate-spin" />
        Queued · waiting for a pipeline slot ({fmtSeconds(elapsedSince(startedAt))})
      </div>
    );
  }
  return (
    <ol className={cn("space-y-1", compact ? "text-[13px]" : "text-sm")}>
      {names.map((name) => {
        const d = done.get(name);
        const isRunning = running?.name === name;
        return (
          <li
            key={name}
            className={cn("flex items-center gap-2", !d && !isRunning && "text-ink-3")}
          >
            {d ? (
              <Check size={15} className="text-ok" />
            ) : isRunning ? (
              <Loader2 size={15} className="animate-spin text-case" />
            ) : (
              <CircleDashed size={15} />
            )}
            <span className={cn(isRunning && "font-medium")}>{stepLabel(name)}</span>
            <span className="num ml-auto text-[12px] text-ink-3">
              {d
                ? fmtSeconds(d.seconds)
                : isRunning && running
                  ? fmtSeconds(elapsedSince(running.started_at))
                  : ""}
            </span>
          </li>
        );
      })}
    </ol>
  );
}

export function StepTimeline({ steps }: { steps: StepRecord[] }) {
  const total = steps.reduce((a, s) => a + (s.seconds ?? 0), 0) || 1;
  return (
    <ol className="space-y-2">
      {steps.map((s) => (
        <li key={`${s.name}-${s.started_at}`} className="grid grid-cols-[1fr_auto] gap-x-3 text-sm">
          <div>
            <div className="flex items-center gap-2">
              <span className="font-medium">{stepLabel(s.name)}</span>
              <span className="num text-[12px] text-ink-3">{fmtSeconds(s.seconds)}</span>
            </div>
            <div className="mt-1 h-1 rounded-full bg-surface-2">
              <div
                className="h-1 rounded-full bg-ink-3"
                style={{ width: `${Math.max(1, ((s.seconds ?? 0) / total) * 100)}%` }}
              />
            </div>
            {Object.keys(s.params ?? {}).length > 0 && (
              <div className="mt-1 font-mono text-[11px] text-ink-3 break-all">
                {Object.entries(s.params ?? {})
                  .filter(([k]) => !["counts", "annotation"].includes(k))
                  .map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : String(v)}`)
                  .join("  ")}
              </div>
            )}
            {(s.warnings ?? []).length > 0 && (
              <ul className="mt-1 list-disc pl-5 text-[12px] text-amber">
                {(s.warnings ?? []).map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            )}
          </div>
        </li>
      ))}
    </ol>
  );
}

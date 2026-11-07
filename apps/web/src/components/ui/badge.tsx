import { Loader2 } from "lucide-react";
import type { HTMLAttributes } from "react";
import type { Tone } from "@/lib/format";
import { statusLabel, statusTone } from "@/lib/format";
import { cn } from "@/lib/utils";

export { Tag } from "./card";

const tones: Record<Tone, string> = {
  case: "border-case/40 bg-case-soft text-case",
  control: "border-control/40 bg-control-soft text-control",
  muted: "border-line-2 bg-surface-2 text-ink-2",
  danger: "border-danger/40 bg-danger-soft text-danger",
  amber: "border-amber/40 bg-amber-soft text-amber",
  ok: "border-accent/40 bg-accent-soft text-accent-ink",
  neutral: "border-line-2 bg-surface-2 text-ink-2",
};

/** A small bordered tag; every word capitalised. */
export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "tag inline-flex h-[22px] items-center gap-1 whitespace-nowrap rounded-md border px-2 text-[12px] font-semibold leading-none",
        tones[tone],
        className,
      )}
      {...props}
    />
  );
}

/** A run, dataset or comparison status as a bordered chip with a dot. */
export function StatusChip({ status, busy }: { status: string; busy?: boolean }) {
  const tone = statusTone(status);
  const color = {
    ok: "border-accent/45 text-accent-ink",
    amber: "border-amber/45 text-amber",
    danger: "border-danger/45 text-danger",
    neutral: "border-line-2 text-ink-2",
    case: "border-line-2 text-ink-2",
    control: "border-line-2 text-ink-2",
    muted: "border-line-2 text-ink-2",
  }[tone];
  const dot = {
    ok: "bg-accent shadow-[0_0_0_3px_var(--accent-soft)]",
    amber: "bg-amber shadow-[0_0_0_3px_var(--amber-soft)]",
    danger: "bg-danger shadow-[0_0_0_3px_var(--danger-soft)]",
    neutral: "bg-ink-3 shadow-[0_0_0_3px_var(--surface-2)]",
    case: "bg-ink-3",
    control: "bg-ink-3",
    muted: "bg-ink-3",
  }[tone];
  return (
    <span
      className={cn(
        "pill inline-flex h-[26px] shrink-0 items-center gap-2 whitespace-nowrap rounded-md border bg-surface px-2.5 text-[12px] font-semibold",
        color,
      )}
    >
      {busy ? (
        <Loader2 size={12} className="animate-spin" />
      ) : (
        <span className={cn("h-[7px] w-[7px] rounded-full", dot)} />
      )}
      {statusLabel(status)}
    </span>
  );
}

/** A small removable or static token, e.g. a gene symbol or a QC flag. */
export function Chip({
  children,
  onRemove,
  tone = "neutral",
  className,
}: {
  children: React.ReactNode;
  onRemove?: () => void;
  tone?: Tone;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex h-7 items-center gap-1 rounded-md border px-2.5 text-[13px] font-medium",
        tones[tone],
        className,
      )}
    >
      {children}
      {onRemove && (
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove"
          className="-mr-1 ml-0.5 rounded px-1 leading-none hover:bg-black/10"
        >
          ×
        </button>
      )}
    </span>
  );
}

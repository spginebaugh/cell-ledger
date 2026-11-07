import type { HTMLAttributes } from "react";
import type { Tone } from "@/lib/format";
import { cn } from "@/lib/utils";

const tones: Record<Tone, string> = {
  case: "bg-case-soft text-case",
  control: "bg-control-soft text-control",
  muted: "bg-surface-2 text-ink-2",
  danger: "bg-danger-soft text-danger",
  amber: "bg-amber-soft text-amber",
  ok: "bg-ok-soft text-ok",
  neutral: "bg-surface-2 text-ink-2 border border-line",
};

export function Badge({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: Tone }) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-sm px-1.5 py-0.5 text-[12px] font-medium leading-4",
        tones[tone],
        className,
      )}
      {...props}
    />
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
        "inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-[13px]",
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
          className="ml-0.5 -mr-1 rounded-full px-1 leading-none hover:bg-black/10"
        >
          ×
        </button>
      )}
    </span>
  );
}

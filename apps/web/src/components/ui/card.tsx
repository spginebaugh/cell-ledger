import { Info } from "lucide-react";
import { type HTMLAttributes, type ReactNode, useEffect, useId, useState } from "react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("rounded-lg border border-line bg-surface", className)}
      style={{ boxShadow: "var(--shadow)" }}
      {...props}
    />
  );
}

/** A bordered panel: the instrument surface every section sits on. */
export function Panel({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("min-w-0 rounded-lg border border-line bg-surface p-4", className)}
      style={{ boxShadow: "var(--shadow)" }}
      {...props}
    />
  );
}

/** Section heading: serif h2, optional lede, or the lede behind an (i) tooltip when `info` is set. */
export function Section({
  title,
  description,
  info,
  actions,
  children,
  className,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  info?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  const tipId = useId();
  const [open, setOpen] = useState(false);
  useEffect(() => {
    if (!open) return;
    const close = () => setOpen(false);
    document.addEventListener("click", close);
    return () => document.removeEventListener("click", close);
  }, [open]);
  return (
    <section id={id} className={cn("mt-12", className)}>
      <div className="relative mb-4 flex flex-wrap items-center gap-3">
        <h2>{title}</h2>
        {info && (
          <>
            <button
              type="button"
              aria-label="About this section"
              aria-expanded={open}
              aria-controls={tipId}
              onClick={(e) => {
                e.stopPropagation();
                setOpen((o) => !o);
              }}
              className={cn(
                "peer inline-grid h-[22px] w-[22px] place-items-center rounded-full border border-line-2 bg-surface text-ink-3 hover:border-accent hover:text-accent-ink",
                open && "border-accent text-accent-ink",
              )}
            >
              <Info size={13} />
            </button>
            <p
              id={tipId}
              role="tooltip"
              className={cn(
                "invisible absolute left-0 top-full z-20 mt-1.5 max-w-[min(60ch,100%)] rounded-md border border-line-2 bg-surface-3 px-3 py-2 text-[13px] text-ink opacity-0 shadow-lg transition-opacity peer-hover:visible peer-hover:opacity-100 peer-focus-visible:visible peer-focus-visible:opacity-100",
                open && "visible opacity-100",
              )}
            >
              {info}
            </p>
          </>
        )}
        {actions && <div className="ml-auto flex items-center gap-2">{actions}</div>}
        {description && <p className="w-full text-[13px] text-ink-2">{description}</p>}
      </div>
      {children}
    </section>
  );
}

/** Small bordered label (Case, Control, Not tested, a column label). */
export function Tag({
  tone = "neutral",
  className,
  ...props
}: HTMLAttributes<HTMLSpanElement> & { tone?: "neutral" | "case" | "control" | "ok" | "muted" }) {
  const tones = {
    neutral: "border-line-2 bg-surface-2 text-ink-2",
    muted: "border-line-2 bg-surface-2 text-ink-2",
    case: "border-case/40 bg-case-soft text-case",
    control: "border-control/40 bg-control-soft text-control",
    ok: "border-accent/40 bg-accent-soft text-accent-ink",
  }[tone];
  return (
    <span
      className={cn(
        "tag inline-flex h-[22px] items-center whitespace-nowrap rounded-md border px-2 text-[12px] font-semibold",
        tones,
        className,
      )}
      {...props}
    />
  );
}

/** Labelled value in a bordered pill: an uppercase key, then the value. */
export function Pill({
  label,
  children,
  mono,
  className,
}: {
  label: string;
  children: ReactNode;
  mono?: boolean;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex min-h-[26px] max-w-full items-center gap-1.5 rounded-md border border-line-2 bg-surface px-2.5 py-[3px] text-[12px] text-ink",
        className,
      )}
    >
      <span className="font-semibold uppercase tracking-[.06em] text-ink-2">{label}:</span>
      <span className={cn("min-w-0 leading-[1.4]", mono ? "truncate font-mono" : "")}>
        {children}
      </span>
    </span>
  );
}

/** A column header inside a panel. */
export function ColHead({ label, detail }: { label: ReactNode; detail?: ReactNode }) {
  return (
    <div className="mb-4 flex items-center justify-between gap-3">
      <Tag>{label}</Tag>
      {detail && <span className="text-[12px] text-ink-3">{detail}</span>}
    </div>
  );
}

export function Empty({ title, children }: { title: ReactNode; children?: ReactNode }) {
  return (
    <div className="rounded-lg border border-dashed border-line-2 px-5 py-8 text-center">
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 text-sm text-ink-2">{children}</div>}
    </div>
  );
}

export function ErrorBox({
  title = "Something went wrong",
  children,
}: {
  title?: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      role="alert"
      className="rounded-md border border-danger/30 bg-danger-soft px-4 py-3 text-sm text-danger"
    >
      <p className="font-medium">{title}</p>
      <div className="mt-0.5 break-words">{children}</div>
    </div>
  );
}

export function Notice({
  tone,
  title,
  children,
  actions,
}: {
  tone: "danger" | "amber" | "ok" | "neutral";
  title: ReactNode;
  children?: ReactNode;
  actions?: ReactNode;
}) {
  const edge = {
    danger: "border-l-danger",
    amber: "border-l-amber",
    ok: "border-l-accent",
    neutral: "border-l-line-2",
  }[tone];
  const head = {
    danger: "text-danger",
    amber: "text-amber",
    ok: "text-accent-ink",
    neutral: "text-ink",
  }[tone];
  return (
    <div
      className={cn(
        "rounded-md border border-line border-l-[3px] bg-surface px-4 py-3 text-[13px]",
        edge,
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-4">
        <div className="min-w-0">
          <h3 className={head}>{title}</h3>
          {children && (
            <div className="mt-0.5 text-ink-2 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:mt-0.5">
              {children}
            </div>
          )}
        </div>
        {actions}
      </div>
    </div>
  );
}

/** A plain disclosure: a chevron and a label, body below. */
export function Details({
  summary,
  children,
  defaultOpen = false,
  className,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
  className?: string;
}) {
  return (
    <details className={cn("group", className)} open={defaultOpen}>
      <summary className="inline-flex cursor-pointer list-none select-none items-center gap-2 py-1 text-[13px] font-medium text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden">
        <span className="inline-block h-1.5 w-1.5 -rotate-45 border-b-[1.5px] border-r-[1.5px] border-ink-3 transition-transform group-open:rotate-45" />
        {summary}
      </summary>
      <div className="mt-2 text-[13px] text-ink-2">{children}</div>
    </details>
  );
}

export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("pulse rounded-md bg-surface-2", className)} aria-hidden />;
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: ReactNode;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div>
      <div className="text-[13px] text-ink-2">{label}</div>
      <div className="num mt-0.5 text-[1.05rem] font-medium leading-tight">{value}</div>
      {hint && <div className="text-[12px] text-ink-3">{hint}</div>}
    </div>
  );
}

/** Label/value rows on hairlines, value right-aligned. */
export function KeyValues({
  rows,
  className,
}: {
  rows: { k: ReactNode; v: ReactNode }[];
  className?: string;
}) {
  return (
    <dl className={cn("m-0 grid grid-cols-[max-content_minmax(0,1fr)] text-[13px]", className)}>
      {rows.map((r, i) => (
        <div key={typeof r.k === "string" ? r.k : i} className="contents">
          <dt className={cn("py-[7px] pr-6 text-ink-2", i > 0 ? "border-t border-line" : "pt-0")}>
            {r.k}
          </dt>
          <dd
            className={cn(
              "num m-0 min-w-0 break-words py-[7px] text-right",
              i > 0 ? "border-t border-line" : "pt-0",
            )}
          >
            {r.v}
          </dd>
        </div>
      ))}
    </dl>
  );
}

import type { HTMLAttributes, ReactNode } from "react";
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

/** A page section: serif heading, optional description, optional right-side actions. */
export function Section({
  title,
  description,
  actions,
  children,
  className,
  id,
}: {
  title: ReactNode;
  description?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
  id?: string;
}) {
  return (
    <section id={id} className={cn("mt-10", className)}>
      <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div className="max-w-[70ch]">
          <h2>{title}</h2>
          {description && <p className="mt-1 text-sm text-ink-2">{description}</p>}
        </div>
        {actions && <div className="flex items-center gap-2">{actions}</div>}
      </div>
      {children}
    </section>
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
}: {
  tone: "danger" | "amber" | "ok" | "neutral";
  title: ReactNode;
  children?: ReactNode;
}) {
  const cls = {
    danger: "bg-danger-soft text-danger border-danger/25",
    amber: "bg-amber-soft text-amber border-amber/25",
    ok: "bg-ok-soft text-ok border-ok/25",
    neutral: "bg-surface-2 text-ink-2 border-line",
  }[tone];
  return (
    <div className={cn("rounded-md border px-4 py-3 text-sm", cls)}>
      <p className="font-medium">{title}</p>
      {children && (
        <div className="mt-1 [&_ul]:list-disc [&_ul]:pl-5 [&_li]:mt-0.5">{children}</div>
      )}
    </div>
  );
}

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
    <details
      className={cn("group rounded-md border border-line bg-surface", className)}
      open={defaultOpen}
    >
      <summary className="cursor-pointer select-none px-4 py-2.5 text-sm font-medium text-ink-2 hover:text-ink [&::-webkit-details-marker]:hidden list-none flex items-center gap-2">
        <span className="inline-block w-3 text-ink-3 transition-transform group-open:rotate-90">
          ›
        </span>
        {summary}
      </summary>
      <div className="border-t border-line px-4 py-3">{children}</div>
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

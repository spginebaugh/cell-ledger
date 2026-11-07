import { Link } from "@tanstack/react-router";
import { Check, Copy, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";
import { cn } from "@/lib/utils";

/** A cell drawn freehand: irregular membrane, off-centre nucleus with nucleolus, two organelles. */
export function CellMark({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" aria-hidden="true" className={className}>
      <path
        d="M15.5 3.2c5.6-.9 11.2 2.6 12.6 8.3 1 4.1-.4 7.9-.1 12 .3 3.4-2.7 5.9-6.2 6.3-5.6.7-11.8-.1-15.6-4.4C2.3 21 2.6 14.1 5.6 9.4c2.2-3.5 5.8-5.5 9.9-6.2Z"
        fill="var(--accent-soft)"
        stroke="var(--accent)"
        strokeWidth={1.6}
        strokeLinejoin="round"
      />
      <path
        d="M12.6 10.3c3.5-1.9 8.3-.5 9.3 3.4.9 3.6-1.5 7.3-5.2 7.9-3.4.5-6.7-1.6-7.1-5-.3-2.6 1-5.2 3-6.3Z"
        fill="var(--surface)"
        stroke="var(--accent)"
        strokeWidth={1.4}
        strokeLinejoin="round"
      />
      <circle cx={17.1} cy={15.4} r={1.7} fill="var(--accent)" />
      <path
        d="M7.6 22.4c1.3-1.4 3.6-1.2 4.6.3-1.6.6-3.3.7-4.6-.3Z"
        fill="var(--accent)"
        opacity={0.75}
      />
      <path
        d="M22.8 8.2c.9-.6 2.1-.3 2.4.7-.9.4-1.9.2-2.4-.7Z"
        fill="var(--accent)"
        opacity={0.75}
      />
    </svg>
  );
}

/** "cell ledger": bold upright, then bold italic. */
export function Wordmark({ className, size = 28 }: { className?: string; size?: number }) {
  return (
    <span
      className={cn("font-display leading-none tracking-[-0.012em]", className)}
      style={{ fontSize: size, fontVariationSettings: '"opsz" 36' }}
    >
      <span className="font-bold text-ink-2">cell</span>{" "}
      <span className="font-bold italic text-ink">ledger</span>
    </span>
  );
}

export function TopBar({ sessionId }: { sessionId?: string }) {
  const { resolved, toggle } = useTheme();
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    if (!sessionId) return;
    try {
      await navigator.clipboard.writeText(sessionId);
      setCopied(true);
      setTimeout(() => setCopied(false), 1200);
    } catch {
      // clipboard blocked; nothing to do
    }
  };
  return (
    <header className="sticky top-0 z-10 border-b border-line bg-surface">
      <div className="flex h-16 w-full items-center justify-between gap-4 px-[var(--gutter)]">
        <Link to="/" className="inline-flex items-center gap-3 no-underline">
          <CellMark className="h-10 w-10 shrink-0" />
          <Wordmark />
        </Link>
        <div className="flex items-center gap-2">
          <Link
            to="/evals"
            className="inline-flex h-[34px] items-center rounded-md border border-transparent px-3 text-[13px] font-semibold text-ink-2 no-underline hover:border-line-2 hover:text-ink"
            activeProps={{ className: "border-line-2 text-ink", "aria-current": "page" }}
          >
            Evals
          </Link>
          {sessionId && (
            <button
              type="button"
              onClick={copy}
              title="Copy session id"
              className="hidden h-[34px] items-center gap-1.5 rounded-md border border-line-2 bg-surface px-3 font-mono text-[13px] text-ink-2 hover:border-accent hover:text-ink sm:inline-flex"
            >
              <span className="text-ink-3">Session</span>
              <span className="max-w-[9ch] truncate md:max-w-none">{sessionId}</span>
              {copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            aria-label={`Switch to ${resolved === "dark" ? "light" : "dark"} theme`}
          >
            {resolved === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </Button>
        </div>
      </div>
    </header>
  );
}

export function Page({
  children,
  width = "wide",
}: {
  children: React.ReactNode;
  width?: "wide" | "narrow";
}) {
  return (
    <main
      className={cn(
        "w-full pb-20 pt-6",
        width === "wide" ? "px-[var(--gutter-page)]" : "mx-auto max-w-[760px] px-4 pt-10",
      )}
    >
      {children}
    </main>
  );
}

export function Footer() {
  return (
    <footer className="mt-12 flex flex-col items-center gap-2 border-t border-line pt-8 text-center">
      <Link to="/" className="no-underline">
        <Wordmark size={18} />
      </Link>
      <p className="max-w-[60ch] text-[13px] text-ink-2">
        Reproducible two-group analysis of public RNA-seq, with every number traceable to a file.
      </p>
      <ul className="mt-2 flex flex-wrap justify-center text-[12px] text-ink-3">
        <li className="px-3">
          <a
            href="https://www.ncbi.nlm.nih.gov/geo/"
            target="_blank"
            rel="noreferrer"
            className="text-accent-ink no-underline hover:underline"
          >
            Data from NCBI GEO
          </a>
        </li>
        <li className="border-l border-line-2 px-3 font-mono">v0.1.0</li>
      </ul>
    </footer>
  );
}

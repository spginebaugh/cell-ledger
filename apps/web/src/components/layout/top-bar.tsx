import { Link } from "@tanstack/react-router";
import { Check, Copy, Moon, Sun } from "lucide-react";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useTheme } from "@/lib/theme";

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
    <header className="border-b border-line bg-surface/80 backdrop-blur">
      <div className="mx-auto flex h-14 max-w-[1280px] items-center justify-between gap-4 px-4">
        <Link
          to="/"
          className="font-display text-[1.25rem] font-medium tracking-tight no-underline"
        >
          cell-ledger
        </Link>
        <div className="flex items-center gap-2">
          <Link
            to="/evals"
            className="rounded-md px-2 py-1 text-[14px] text-ink-2 no-underline hover:bg-surface-2 hover:text-ink"
            activeProps={{ className: "text-ink font-medium", "aria-current": "page" }}
          >
            evals
          </Link>
          {sessionId && (
            <button
              type="button"
              onClick={copy}
              title="Copy session id"
              className="accession hidden items-center gap-1.5 rounded-md border border-line px-2 py-1 text-[12px] text-ink-2 hover:bg-surface-2 sm:inline-flex"
            >
              <span className="text-ink-3">session</span>
              {sessionId.slice(0, 8)}…{copied ? <Check size={13} /> : <Copy size={13} />}
            </button>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={toggle}
            aria-label={`Switch to ${resolved === "dark" ? "light" : "dark"} theme`}
          >
            {resolved === "dark" ? <Sun size={17} /> : <Moon size={17} />}
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
      className={
        width === "wide"
          ? "mx-auto w-full max-w-[1280px] px-4 pb-20 pt-8"
          : "mx-auto w-full max-w-[760px] px-4 pb-20 pt-10"
      }
    >
      {children}
    </main>
  );
}

import { Dialog as RD } from "radix-ui";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export function Dialog({
  open,
  onOpenChange,
  title,
  description,
  children,
  className,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <RD.Root open={open} onOpenChange={onOpenChange}>
      <RD.Portal>
        <RD.Overlay className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]" />
        <RD.Content
          className={cn(
            "fixed left-1/2 top-1/2 z-50 max-h-[90vh] w-[min(92vw,640px)] -translate-x-1/2 -translate-y-1/2 overflow-y-auto rounded-lg border border-line bg-surface p-6 shadow-xl focus:outline-none",
            className,
          )}
        >
          <RD.Title asChild>
            <h2>{title}</h2>
          </RD.Title>
          {description ? (
            <RD.Description className="mt-1 text-sm text-ink-2">{description}</RD.Description>
          ) : (
            <RD.Description className="sr-only">Dialog</RD.Description>
          )}
          <div className="mt-5">{children}</div>
          <RD.Close asChild>
            <button
              type="button"
              aria-label="Close"
              className="absolute right-3 top-3 rounded-md px-2 py-1 text-ink-3 hover:bg-surface-2 hover:text-ink"
            >
              ×
            </button>
          </RD.Close>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

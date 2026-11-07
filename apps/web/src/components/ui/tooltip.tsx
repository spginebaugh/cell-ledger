import type { ReactNode } from "react";

/** Positioned hover readout for charts: render inside a `relative` container. */
export function ChartTip({
  x,
  y,
  width,
  children,
}: {
  x: number;
  y: number;
  width: number;
  children: ReactNode;
}) {
  const flip = x > width * 0.6;
  return (
    <div
      role="status"
      className="pointer-events-none absolute z-10 max-w-[260px] rounded-md border border-line bg-surface px-2.5 py-1.5 text-[12px] leading-snug text-ink shadow-md"
      style={{
        left: flip ? undefined : x + 12,
        right: flip ? width - x + 12 : undefined,
        top: Math.max(0, y - 8),
      }}
    >
      {children}
    </div>
  );
}

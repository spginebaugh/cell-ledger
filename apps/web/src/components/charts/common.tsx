import type { ScaleLinear } from "d3-scale";
import { useEffect, useRef, useState } from "react";

/** Observe an element's width so charts can size themselves to their column. */
export function useMeasure<T extends HTMLElement>(): [React.RefObject<T | null>, number] {
  const ref = useRef<T | null>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    setWidth(el.clientWidth);
    const ro = new ResizeObserver((entries) => {
      for (const e of entries) setWidth(e.contentRect.width);
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  return [ref, width];
}

export const CHART = {
  case: "var(--case)",
  control: "var(--control)",
  muted: "var(--muted)",
  ink: "var(--ink)",
  ink2: "var(--ink-2)",
  ink3: "var(--ink-3)",
  grid: "var(--grid)",
  surface: "var(--surface)",
};

export function armColor(arm: string | undefined | null): string {
  if (arm === "case") return CHART.case;
  if (arm === "control") return CHART.control;
  return CHART.muted;
}

/** A plain numeric axis drawn with text tokens and a recessive line. */
export function AxisBottom({
  scale,
  y,
  ticks = 5,
  format = (v: number) => String(v),
  label,
  width,
}: {
  scale: ScaleLinear<number, number>;
  y: number;
  ticks?: number;
  format?: (v: number) => string;
  label?: string;
  width: number;
}) {
  const [x0, x1] = scale.range();
  return (
    <g
      transform={`translate(0,${y})`}
      fontSize={11}
      fill={CHART.ink2}
      fontFamily="var(--font-sans)"
    >
      <line x1={x0} x2={x1} stroke={CHART.grid} />
      {scale.ticks(ticks).map((t) => (
        <g key={t} transform={`translate(${scale(t)},0)`}>
          <line y2={4} stroke={CHART.grid} />
          <text y={16} textAnchor="middle">
            {format(t)}
          </text>
        </g>
      ))}
      {label && (
        <text x={width / 2} y={34} textAnchor="middle" fill={CHART.ink2} fontSize={12}>
          {label}
        </text>
      )}
    </g>
  );
}

export function AxisLeft({
  scale,
  x,
  ticks = 5,
  format = (v: number) => String(v),
  label,
  height,
}: {
  scale: ScaleLinear<number, number>;
  x: number;
  ticks?: number;
  format?: (v: number) => string;
  label?: string;
  height: number;
}) {
  return (
    <g
      transform={`translate(${x},0)`}
      fontSize={11}
      fill={CHART.ink2}
      fontFamily="var(--font-sans)"
    >
      {scale.ticks(ticks).map((t) => (
        <g key={t} transform={`translate(0,${scale(t)})`}>
          <line x2={-4} stroke={CHART.grid} />
          <text x={-8} dy="0.32em" textAnchor="end">
            {format(t)}
          </text>
        </g>
      ))}
      {label && (
        <text
          transform={`translate(${-44},${height / 2}) rotate(-90)`}
          textAnchor="middle"
          fill={CHART.ink2}
          fontSize={12}
        >
          {label}
        </text>
      )}
    </g>
  );
}

export function GridY({
  scale,
  x0,
  x1,
  ticks = 5,
}: {
  scale: ScaleLinear<number, number>;
  x0: number;
  x1: number;
  ticks?: number;
}) {
  return (
    <g>
      {scale.ticks(ticks).map((t) => (
        <line key={t} x1={x0} x2={x1} y1={scale(t)} y2={scale(t)} stroke={CHART.grid} />
      ))}
    </g>
  );
}

export function Legend({
  items,
}: {
  items: { label: string; color: string; shape?: "dot" | "line" }[];
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-2">
      {items.map((it) => (
        <span key={it.label} className="inline-flex items-center gap-1.5">
          {it.shape === "line" ? (
            <span
              className="inline-block h-0 w-4 border-t-2 border-dotted"
              style={{ borderColor: it.color }}
            />
          ) : (
            <span
              className="inline-block h-2.5 w-2.5 rounded-full"
              style={{ background: it.color }}
            />
          )}
          {it.label}
        </span>
      ))}
    </div>
  );
}

/** Deterministic jitter in [-1, 1) from a string, so strip plots are stable across renders. */
export function jitter(key: string): number {
  let h = 2166136261;
  for (let i = 0; i < key.length; i++) {
    h ^= key.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 1000) / 500 - 1;
}

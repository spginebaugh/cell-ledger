import { useState } from "react";
import type { Concordance } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtInt, fmtNum } from "@/lib/format";
import { CHART, useMeasure } from "./common";

type Cell = { i: number; j: number; v: number | null; n: number };

const MIN_CELL = 26;
const MAX_CELL = 56;

/** Pairwise Spearman correlation of Wald statistics between datasets, drawn once per pair as
 * the lower triangle of the matrix. Blue: the two studies ranked their genes the same way;
 * orange: the opposite way, as when one study's case and control labels were swapped. Column
 * names sit in the empty diagonal cells, so nothing is repeated. */
export function ConcordanceHeatmap({ concordance }: { concordance: Concordance }) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ c: Cell; x: number; y: number } | null>(null);
  const names = concordance.members;
  const n = names.length;
  const short = (l: string) => l.split(":")[0];
  const labelW = Math.min(110, Math.max(72, width * 0.16));
  const avail = width - labelW - 8;
  const cell = Math.max(MIN_CELL, Math.min(MAX_CELL, avail / Math.max(1, n)));
  const fontSize = cell >= 40 ? 11 : 10;
  // the column names run up the diagonal at 45°, so the first needs headroom above row 0
  const longest = Math.max(0, ...names.slice(0, -1).map((l) => short(l).length));
  const top = Math.max(10, Math.ceil(longest * fontSize * 0.62 * 0.72 - cell / 2 + 10));
  const svgW = Math.max(width, labelW + n * cell + 8);
  const height = top + n * cell + 8;

  const color = (v: number | null) => {
    if (v === null || Number.isNaN(v)) return "var(--surface-2)";
    const t = Math.max(-1, Math.min(1, v));
    // diverging: control orange (negative) → surface (zero) → case blue (positive)
    return t >= 0
      ? `color-mix(in oklab, var(--case) ${Math.round(t * 85)}%, var(--surface))`
      : `color-mix(in oklab, var(--control) ${Math.round(-t * 85)}%, var(--surface))`;
  };

  const cells: Cell[] = [];
  for (let i = 1; i < n; i++)
    for (let j = 0; j < i; j++)
      cells.push({
        i,
        j,
        v: concordance.spearman[i]?.[j] ?? null,
        n: concordance.n_shared[i]?.[j] ?? 0,
      });

  const cx = (j: number) => labelW + j * cell;
  const cy = (i: number) => top + i * cell;

  if (n < 2) return <p className="text-sm text-ink-3">Agreement needs at least two datasets.</p>;

  return (
    <div ref={ref} className="relative w-full overflow-x-auto">
      {width > 0 && (
        <svg
          width={svgW}
          height={height}
          role="img"
          aria-label={`Agreement between ${n} datasets, one cell per pair`}
        >
          {/* row names: every dataset but the first, which has no row in a lower triangle */}
          {names.slice(1).map((row, k) => (
            <text
              key={row}
              x={labelW - 8}
              y={cy(k + 1) + cell / 2}
              dy="0.32em"
              textAnchor="end"
              fontSize={fontSize}
              fill={CHART.ink2}
              fontFamily="var(--font-mono)"
            >
              {short(row)}
            </text>
          ))}
          {/* column names in the empty diagonal cells, read along the diagonal */}
          {names.slice(0, -1).map((col, j) => (
            <text
              key={col}
              transform={`translate(${cx(j) + cell / 2 - 2},${cy(j) + cell / 2 + 4}) rotate(-45)`}
              textAnchor="start"
              fontSize={fontSize}
              fill={CHART.ink2}
              fontFamily="var(--font-mono)"
            >
              {short(col)}
            </text>
          ))}
          {cells.map((c) => (
            <g
              key={`${c.i}-${c.j}`}
              role="graphics-symbol"
              aria-label={`${short(names[c.i])} vs ${short(names[c.j])}: ${c.v === null ? "not compared" : fmtNum(c.v)}`}
              onMouseMove={(e) => {
                const rect = (
                  e.currentTarget.ownerSVGElement as SVGSVGElement
                ).getBoundingClientRect();
                setHover({ c, x: e.clientX - rect.left, y: e.clientY - rect.top });
              }}
              onMouseLeave={() => setHover(null)}
            >
              <rect
                x={cx(c.j) + 1}
                y={cy(c.i) + 1}
                width={cell - 2}
                height={cell - 2}
                rx={3}
                fill={color(c.v)}
                stroke={hover?.c === c ? CHART.ink : "none"}
                strokeWidth={1.5}
              />
              {c.v !== null && cell >= 30 && (
                <text
                  x={cx(c.j) + cell / 2}
                  y={cy(c.i) + cell / 2}
                  dy="0.32em"
                  textAnchor="middle"
                  fontSize={fontSize}
                  fill={Math.abs(c.v) > 0.5 ? "white" : CHART.ink}
                  className="num pointer-events-none"
                >
                  {fmtNum(c.v)}
                </text>
              )}
            </g>
          ))}
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="accession font-medium">
            {short(names[hover.c.i])} · {short(names[hover.c.j])}
          </div>
          <div className="num text-ink-2">
            {hover.c.v === null ? "not compared" : `correlation ${fmtNum(hover.c.v)}`}
            {hover.c.n > 0 && <> · {fmtInt(hover.c.n)} genes in both</>}
          </div>
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-2">
        <span className="inline-flex items-center gap-1.5">
          <span
            className="inline-block h-2.5 w-14 rounded-sm"
            style={{
              background: `linear-gradient(to right, ${color(-1)}, ${color(0)}, ${color(1)})`,
            }}
          />
          <span className="num">−1 opposite · 0 none · 1 identical</span>
        </span>
      </div>
    </div>
  );
}

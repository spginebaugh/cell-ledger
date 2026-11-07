import type { Concordance } from "@/api/generated/types.gen";
import { fmtNum } from "@/lib/format";
import { useMeasure } from "./common";

/** Pairwise Spearman correlation of Wald statistics; a diverging ramp around zero. */
export function ConcordanceHeatmap({ concordance }: { concordance: Concordance }) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const n = concordance.members.length;
  const labelW = Math.min(170, Math.max(80, width * 0.3));
  const cell = Math.max(28, Math.min(56, (width - labelW) / Math.max(1, n)));
  const height = labelW * 0.6 + n * cell + 8;
  const short = (l: string) => l.split(":")[0];
  const color = (v: number | null) => {
    if (v === null || Number.isNaN(v)) return "var(--surface-2)";
    const t = Math.max(-1, Math.min(1, v));
    // diverging: control orange (negative) → neutral → case blue (positive)
    return t >= 0
      ? `color-mix(in oklab, var(--case) ${Math.round(t * 85)}%, var(--surface))`
      : `color-mix(in oklab, var(--control) ${Math.round(-t * 85)}%, var(--surface))`;
  };
  return (
    <div ref={ref} className="w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Concordance between datasets">
          {concordance.members.map((row, i) => (
            <g key={row}>
              <text
                x={labelW - 8}
                y={labelW * 0.6 + i * cell + cell / 2}
                dy="0.32em"
                textAnchor="end"
                fontSize={11}
                fill="var(--ink-2)"
                fontFamily="var(--font-mono)"
              >
                {short(row)}
              </text>
              {concordance.members.map((col, j) => {
                const v = concordance.spearman[i]?.[j] ?? null;
                return (
                  <g key={col}>
                    <rect
                      x={labelW + j * cell + 1}
                      y={labelW * 0.6 + i * cell + 1}
                      width={cell - 2}
                      height={cell - 2}
                      rx={3}
                      fill={i === j ? "var(--surface-2)" : color(v)}
                    />
                    {i !== j && v !== null && (
                      <text
                        x={labelW + j * cell + cell / 2}
                        y={labelW * 0.6 + i * cell + cell / 2}
                        dy="0.32em"
                        textAnchor="middle"
                        fontSize={11}
                        fill={Math.abs(v) > 0.5 ? "white" : "var(--ink)"}
                        className="num"
                      >
                        {fmtNum(v)}
                      </text>
                    )}
                  </g>
                );
              })}
            </g>
          ))}
          {concordance.members.map((col, j) => (
            <text
              key={col}
              transform={`translate(${labelW + j * cell + cell / 2},${labelW * 0.6 - 6}) rotate(-35)`}
              fontSize={11}
              fill="var(--ink-2)"
              fontFamily="var(--font-mono)"
            >
              {short(col)}
            </text>
          ))}
        </svg>
      )}
    </div>
  );
}

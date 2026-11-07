import { max } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtInt, fmtMillions } from "@/lib/format";
import { AxisBottom, armColor, CHART, Legend, useMeasure } from "./common";

export type LibRow = { gsm: string; arm: string; librarySize: number; flags: string[] };

export function LibrarySizes({ rows, threshold }: { rows: LibRow[]; threshold: number }) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ row: LibRow; x: number; y: number } | null>(null);
  const sorted = [...rows].sort((a, b) => a.librarySize - b.librarySize);
  const rowH = 18;
  const m = { top: 6, right: 16, bottom: 44, left: 104 };
  const height = m.top + m.bottom + sorted.length * rowH;
  const innerW = Math.max(10, width - m.left - m.right);
  const xMax = Math.max(threshold * 1.1, (max(sorted, (d) => d.librarySize) ?? 0) * 1.05);
  const x = scaleLinear()
    .domain([0, xMax])
    .range([m.left, m.left + innerW])
    .nice();

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Library size per sample">
          {sorted.map((d, i) => {
            const y = m.top + i * rowH;
            return (
              <g key={d.gsm}>
                <text
                  x={m.left - 8}
                  y={y + rowH / 2}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={11}
                  fill={d.flags.length ? "var(--amber)" : CHART.ink2}
                  fontFamily="var(--font-mono)"
                >
                  {d.gsm}
                </text>
                <rect
                  role="graphics-symbol"
                  aria-label={`${d.gsm}: ${fmtInt(d.librarySize)} reads`}
                  x={x(0)}
                  y={y + 3}
                  width={Math.max(0, x(d.librarySize) - x(0))}
                  height={rowH - 6}
                  rx={2}
                  fill={armColor(d.arm)}
                  opacity={hover && hover.row.gsm !== d.gsm ? 0.55 : 1}
                  onMouseMove={(e) => {
                    const r = (
                      e.currentTarget.ownerSVGElement as SVGSVGElement
                    ).getBoundingClientRect();
                    setHover({ row: d, x: e.clientX - r.left, y: e.clientY - r.top });
                  }}
                  onMouseLeave={() => setHover(null)}
                />
              </g>
            );
          })}
          <line
            x1={x(threshold)}
            x2={x(threshold)}
            y1={m.top}
            y2={height - m.bottom}
            stroke={CHART.ink2}
            strokeDasharray="2 3"
          />
          <AxisBottom
            scale={x}
            y={height - m.bottom + 4}
            width={width}
            format={(v) => fmtMillions(v)}
            label="Assigned reads"
          />
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="accession font-medium">{hover.row.gsm}</div>
          <div>
            {hover.row.arm} · {fmtInt(hover.row.librarySize)} reads
          </div>
          {hover.row.flags.length > 0 && (
            <div className="text-amber">{hover.row.flags.join(", ")}</div>
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Legend
          items={[
            { label: "case", color: CHART.case },
            { label: "control", color: CHART.control },
            {
              label: `low-library threshold (${fmtMillions(threshold)})`,
              color: CHART.ink2,
              shape: "line",
            },
          ]}
        />
      </div>
    </div>
  );
}

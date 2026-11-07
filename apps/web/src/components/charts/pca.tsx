import { extent } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtPct } from "@/lib/format";
import { AxisBottom, AxisLeft, armColor, CHART, GridY, Legend, useMeasure } from "./common";

export type PcaPoint = {
  gsm: string;
  arm: string;
  x: number;
  y: number;
  flags: string[];
  labels: string[]; // harmonized labels to show on hover
};

export function PcaScatter({
  points,
  variance,
  armR2,
}: {
  points: PcaPoint[];
  variance: number[];
  armR2?: number | null;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ p: PcaPoint; x: number; y: number } | null>(null);
  const height = 320;
  const m = { top: 10, right: 16, bottom: 44, left: 56 };
  const pad = (d: [number, number]) => {
    const span = d[1] - d[0] || 1;
    return [d[0] - span * 0.1, d[1] + span * 0.1] as [number, number];
  };
  const xs = extent(points, (p) => p.x) as [number, number];
  const ys = extent(points, (p) => p.y) as [number, number];
  const x = scaleLinear()
    .domain(pad(xs))
    .range([m.left, width - m.right]);
  const y = scaleLinear()
    .domain(pad(ys))
    .range([height - m.bottom, m.top]);

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="PCA of samples">
          <GridY scale={y} x0={m.left} x1={width - m.right} />
          <AxisLeft
            scale={y}
            x={m.left}
            height={height}
            label={`PC2 (${fmtPct(variance[1] ?? 0)} of variance)`}
          />
          <AxisBottom
            scale={x}
            y={height - m.bottom}
            width={width}
            label={`PC1 (${fmtPct(variance[0] ?? 0)} of variance)`}
          />
          {points.map((p) => (
            <g key={p.gsm}>
              <circle
                role="graphics-symbol"
                aria-label={`${p.gsm} (${p.arm})`}
                cx={x(p.x)}
                cy={y(p.y)}
                r={hover?.p.gsm === p.gsm ? 7 : 5.5}
                fill={armColor(p.arm)}
                stroke={CHART.surface}
                strokeWidth={1.5}
                onMouseMove={(e) => {
                  const r = (
                    e.currentTarget.ownerSVGElement as SVGSVGElement
                  ).getBoundingClientRect();
                  setHover({ p, x: e.clientX - r.left, y: e.clientY - r.top });
                }}
                onMouseLeave={() => setHover(null)}
              />
              {p.flags.length > 0 && (
                <text
                  x={x(p.x) + 8}
                  y={y(p.y) - 6}
                  fontSize={10}
                  fill={CHART.ink2}
                  fontFamily="var(--font-mono)"
                >
                  {p.gsm}
                </text>
              )}
            </g>
          ))}
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="accession font-medium">{hover.p.gsm}</div>
          <div className="capitalize">{hover.p.arm}</div>
          {hover.p.labels.length > 0 && (
            <div className="text-ink-2">{hover.p.labels.join(" · ")}</div>
          )}
          {hover.p.flags.length > 0 && <div className="text-amber">{hover.p.flags.join(", ")}</div>}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Legend
          items={[
            { label: "case", color: CHART.case },
            { label: "control", color: CHART.control },
          ]}
        />
        {armR2 !== null && armR2 !== undefined && (
          <span className="text-[12px] text-ink-2">arm explains {fmtPct(armR2)} of PC1</span>
        )}
      </div>
    </div>
  );
}

import { extent, mean } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtNum } from "@/lib/format";
import { AxisLeft, armColor, CHART, GridY, jitter, useMeasure } from "./common";

export type StripPoint = {
  /** A GSM, or the id of a fitted observation that summed several GSMs (then `members` lists them). */
  gsm: string;
  arm: "case" | "control" | string;
  value: number;
  members?: string[];
};

export function StripPlot({
  points,
  caseLabel,
  controlLabel,
  height = 220,
}: {
  points: StripPoint[];
  caseLabel: string;
  controlLabel: string;
  height?: number;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ p: StripPoint; x: number; y: number } | null>(null);
  const m = { top: 10, right: 10, bottom: 40, left: 48 };
  const [lo, hi] = extent(points, (p) => p.value) as [number, number];
  const span = hi - lo || 1;
  const y = scaleLinear()
    .domain([Math.max(0, lo - span * 0.15), hi + span * 0.15])
    .range([height - m.bottom, m.top])
    .nice();
  const arms = ["control", "case"];
  const cx = (arm: string) => {
    const w = width - m.left - m.right;
    return m.left + w * (arm === "control" ? 0.3 : 0.7);
  };
  const halfW = Math.max(14, (width - m.left - m.right) * 0.12);
  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg width={width} height={height} role="img" aria-label="Per-sample expression by arm">
          <GridY scale={y} x0={m.left} x1={width - m.right} ticks={4} />
          <AxisLeft scale={y} x={m.left} ticks={4} height={height} />
          {arms.map((arm) => {
            const vals = points.filter((p) => p.arm === arm);
            const mu = mean(vals, (p) => p.value);
            return (
              <g key={arm}>
                {mu !== undefined && (
                  <line
                    x1={cx(arm) - halfW}
                    x2={cx(arm) + halfW}
                    y1={y(mu)}
                    y2={y(mu)}
                    stroke={CHART.ink}
                    strokeWidth={2}
                  />
                )}
                {vals.map((p) => (
                  <circle
                    key={p.gsm}
                    role="graphics-symbol"
                    aria-label={`${p.gsm}: ${fmtNum(p.value)}`}
                    cx={cx(arm) + jitter(p.gsm) * halfW * 0.7}
                    cy={y(p.value)}
                    r={5}
                    fill={armColor(arm)}
                    stroke={CHART.surface}
                    strokeWidth={1.2}
                    onMouseMove={(e) => {
                      const r = (
                        e.currentTarget.ownerSVGElement as SVGSVGElement
                      ).getBoundingClientRect();
                      setHover({ p, x: e.clientX - r.left, y: e.clientY - r.top });
                    }}
                    onMouseLeave={() => setHover(null)}
                  />
                ))}
                <text
                  x={cx(arm)}
                  y={height - m.bottom + 18}
                  textAnchor="middle"
                  fontSize={11}
                  fill={CHART.ink2}
                >
                  {arm === "case" ? "case" : "control"}
                </text>
                <text
                  visibility="hidden"
                  x={cx(arm)}
                  y={height - m.bottom + 31}
                  textAnchor="middle"
                  fontSize={10}
                  fill={CHART.ink3}
                >
                  {truncate(arm === "case" ? caseLabel : controlLabel, Math.floor(width / 14))}
                </text>
              </g>
            );
          })}
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="accession font-medium">{hover.p.gsm}</div>
          <div>
            {hover.p.arm} · log2 {fmtNum(hover.p.value)}
          </div>
          {hover.p.members && (
            <div className="accession mt-0.5 text-[11px]">
              sum of {hover.p.members.length} samples: {hover.p.members.join(", ")}
            </div>
          )}
        </ChartTip>
      )}
    </div>
  );
}

function truncate(s: string, n: number) {
  return s.length > n ? `${s.slice(0, Math.max(3, n - 1))}…` : s;
}

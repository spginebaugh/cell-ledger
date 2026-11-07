import { extent } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useMemo, useState } from "react";
import type { QcResult, SampleQc } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtMillions, fmtNum } from "@/lib/format";
import { AxisBottom, AxisLeft, armColor, CHART, GridY, Legend, useMeasure } from "./common";

type Point = { s: SampleQc; x: number; y: number; flagged: boolean };

/** Every sample as a point in the first two principal components, coloured by arm.
 * The PCA never saw the arms: if the clouds separate, the groups really differ. */
export function PcaScatter({
  qc,
  caseLabel,
  controlLabel,
  height = 360,
}: {
  qc: QcResult;
  caseLabel: string;
  controlLabel: string;
  height?: number;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ p: Point; x: number; y: number } | null>(null);
  const m = { top: 12, right: 16, bottom: 44, left: 56 };
  const pca = qc.pca;

  const points = useMemo<Point[]>(() => {
    if (!pca) return [];
    return qc.samples
      .filter((s) => pca.coords[s.gsm])
      .map((s) => ({
        s,
        x: pca.coords[s.gsm][0],
        y: pca.coords[s.gsm][1],
        flagged: (s.flags ?? []).length > 0,
      }));
  }, [qc, pca]);

  const [x0, x1] = extent(points, (p) => p.x) as [number, number];
  const [y0, y1] = extent(points, (p) => p.y) as [number, number];
  const pad = (lo: number, hi: number) => {
    const span = hi - lo || 1;
    return [lo - span * 0.08, hi + span * 0.08] as [number, number];
  };
  const x = scaleLinear()
    .domain(pad(x0 ?? -1, x1 ?? 1))
    .range([m.left, width - m.right])
    .nice();
  const y = scaleLinear()
    .domain(pad(y0 ?? -1, y1 ?? 1))
    .range([height - m.bottom, m.top])
    .nice();

  if (!pca || points.length === 0)
    return <p className="text-sm text-ink-3">Too few samples for a PCA.</p>;

  const pct = (i: number) => `${Math.round((pca.variance_ratio[i] ?? 0) * 100)}%`;
  const nCase = points.filter((p) => p.s.arm === "case").length;
  const nControl = points.filter((p) => p.s.arm === "control").length;
  const nFlagged = points.filter((p) => p.flagged).length;
  const r2 = pca.arm_r2_pc1;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`PCA of ${points.length} samples: ${nCase} case, ${nControl} control`}
        >
          <GridY scale={y} x0={m.left} x1={width - m.right} ticks={5} />
          <line
            x1={x(0)}
            x2={x(0)}
            y1={m.top}
            y2={height - m.bottom}
            stroke={CHART.grid}
            strokeDasharray="2 3"
          />
          <AxisLeft scale={y} x={m.left} height={height} label={`PC2 (${pct(1)} of variance)`} />
          <AxisBottom
            scale={x}
            y={height - m.bottom}
            width={width}
            label={`PC1 (${pct(0)} of variance)`}
          />
          {/* controls first so the case arm draws on top where they overlap */}
          {[...points]
            .sort((a, b) => (a.s.arm === "case" ? 1 : 0) - (b.s.arm === "case" ? 1 : 0))
            .map((p) => (
              <circle
                key={p.s.gsm}
                role="graphics-symbol"
                aria-label={`${p.s.gsm} (${p.s.arm})`}
                cx={x(p.x)}
                cy={y(p.y)}
                r={points.length > 60 ? 4.5 : 6}
                fill={armColor(p.s.arm)}
                fillOpacity={0.85}
                stroke={p.flagged ? CHART.ink : CHART.surface}
                strokeWidth={p.flagged ? 2 : 1.2}
                strokeDasharray={p.flagged ? "2 1.5" : undefined}
                className="cursor-crosshair"
                onMouseMove={(e) => {
                  const rect = (
                    e.currentTarget.ownerSVGElement as SVGSVGElement
                  ).getBoundingClientRect();
                  setHover({ p, x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseLeave={() => setHover(null)}
              />
            ))}
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="accession font-medium">{hover.p.s.gsm}</div>
          <div className="text-ink-2">
            <span style={{ color: armColor(hover.p.s.arm) }} className="font-medium">
              {hover.p.s.arm === "case" ? caseLabel : controlLabel}
            </span>
          </div>
          <div className="num text-ink-2">
            {fmtMillions(hover.p.s.library_size)} reads ·{" "}
            {hover.p.s.detected_genes.toLocaleString()} genes
            {hover.p.s.predicted_sex && <> · {hover.p.s.predicted_sex}</>}
          </div>
          {(hover.p.s.flags ?? []).length > 0 && (
            <div className="mt-0.5 text-amber">
              {(hover.p.s.flags ?? []).join(", ").replaceAll("_", " ")}
            </div>
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Legend
          items={[
            { label: `${caseLabel} (${nCase})`, color: CHART.case },
            { label: `${controlLabel} (${nControl})`, color: CHART.control },
            ...(nFlagged > 0
              ? [{ label: `${nFlagged} with a QC flag (dashed ring)`, color: CHART.ink }]
              : []),
          ]}
        />
        {r2 != null && (
          <span
            className="num text-[12px] text-ink-3"
            title="Share of PC1 variance explained by arm"
          >
            arm explains {fmtNum(r2 * 100, 0)}% of PC1
          </span>
        )}
      </div>
    </div>
  );
}

import { scaleLinear, scaleSqrt } from "d3-scale";
import { useMemo, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { AxisBottom, CHART, useMeasure } from "./common";
import { termLabel } from "./enrichment-bars";

const MAX_LOG_FDR = 3; // FDR 0.001 is as dark as a dot gets
const fmtFdr = (f: number) => (f < 1e-3 ? "<0.001" : f.toFixed(3));

/** Sequential ramp for confidence: faint at FDR 1, deep purple at FDR ≤ 0.001. Direction is
 * carried by position, so this hue is deliberately neither the case nor the control colour. */
export function fdrColor(fdr: number): string {
  const t = Math.min(1, Math.max(0, -Math.log10(Math.max(fdr, 1e-12)) / MAX_LOG_FDR));
  const pct = Math.round(18 + t * 82);
  return `color-mix(in oklab, var(--z-hi) ${pct}%, var(--surface))`;
}

/** The GSEA dot plot: one circle per gene set, placed by its normalised enrichment score, sized
 * by how many genes are in the set and coloured by FDR. Sets enriched in the case sit right of
 * zero, sets enriched in the control sit left. Click a dot to mark its genes on the volcano. */
export function EnrichmentDots({
  terms,
  selected,
  onSelect,
  caseLabel,
  controlLabel,
  n = 20,
}: {
  terms: EnrichmentTerm[];
  selected: string | null;
  onSelect: (term: EnrichmentTerm | null) => void;
  caseLabel: string;
  controlLabel: string;
  n?: number;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ t: EnrichmentTerm; x: number; y: number } | null>(null);
  // the strongest sets, then ordered by score so the picture reads top-to-bottom
  const shown = useMemo(
    () =>
      [...terms]
        .sort((a, b) => a.fdr - b.fdr || Math.abs(b.nes) - Math.abs(a.nes))
        .slice(0, n)
        .sort((a, b) => b.nes - a.nes),
    [terms, n],
  );
  const labelW = Math.min(240, Math.max(130, width * 0.36));
  const rowH = 28;
  const top = 8;
  const axisH = 44;
  const plotL = labelW + 8;
  const plotR = width - 16;
  const height = top + rowH * shown.length + axisH;
  const nesMax = Math.max(1.5, ...shown.map((t) => Math.abs(t.nes))) * 1.15;
  const x = scaleLinear().domain([-nesMax, nesMax]).range([plotL, plotR]).nice();
  const sizes = shown.map((t) => t.size);
  const sMin = Math.min(...sizes);
  const sMax = Math.max(...sizes);
  const r = scaleSqrt()
    .domain([Math.max(1, sMin), Math.max(2, sMax)])
    .range([4.5, rowH / 2 - 2]);
  const yOf = (i: number) => top + i * rowH + rowH / 2;

  if (shown.length === 0) return null;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`${shown.length} gene sets by normalised enrichment score; circle size is genes in the set, colour is FDR`}
        >
          {shown.map((t, i) => {
            const isSel = selected === t.term;
            const label = termLabel(t.term);
            const cy = yOf(i);
            const anySel = selected !== null && shown.some((s) => s.term === selected);
            return (
              <g
                key={t.term}
                role="graphics-symbol"
                aria-label={`${label}: NES ${fmtNum(t.nes)}, FDR ${fmtFdr(t.fdr)}, ${t.size} genes${isSel ? ", selected" : ""}`}
                className="cursor-pointer"
                opacity={anySel && !isSel ? 0.45 : 1}
                onMouseMove={(e) => {
                  const rect = e.currentTarget.ownerSVGElement?.getBoundingClientRect();
                  if (rect) setHover({ t, x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseLeave={() => setHover(null)}
                onClick={() => onSelect(isSel ? null : t)}
              >
                {/* row hit area and guide */}
                <rect x={0} y={cy - rowH / 2} width={width} height={rowH} fill="transparent" />
                <line
                  x1={plotL}
                  x2={plotR}
                  y1={cy}
                  y2={cy}
                  stroke={CHART.grid}
                  strokeDasharray="2 4"
                />
                <text
                  x={labelW}
                  y={cy}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={12}
                  fontWeight={isSel ? 600 : 400}
                  fill={isSel ? "var(--accent-ink)" : CHART.ink2}
                  className={cn(isSel ? undefined : "hover:fill-[var(--ink)]")}
                >
                  {label.length > 34 ? `${label.slice(0, 33)}…` : label}
                </text>
                {isSel && (
                  <circle
                    cx={x(t.nes)}
                    cy={cy}
                    r={r(t.size) + 4}
                    fill="none"
                    stroke="var(--accent)"
                    strokeWidth={2}
                  />
                )}
                <circle
                  cx={x(t.nes)}
                  cy={cy}
                  r={r(t.size)}
                  fill={fdrColor(t.fdr)}
                  stroke={CHART.ink}
                  strokeOpacity={0.35}
                  strokeWidth={1}
                />
              </g>
            );
          })}
          {/* zero line, over the guides and under nothing */}
          <line
            x1={x(0)}
            x2={x(0)}
            y1={top}
            y2={top + rowH * shown.length}
            stroke={CHART.ink3}
            strokeWidth={1}
          />
          <AxisBottom
            scale={x}
            y={top + rowH * shown.length + 4}
            ticks={Math.max(3, Math.min(7, Math.round((plotR - plotL) / 70)))}
            format={(v) => (v > 0 ? `+${v}` : String(v))}
            width={width}
          />
          <g fontSize={11} fontWeight={600}>
            <text x={plotL} y={height - 2} fill={CHART.control}>
              ← enriched in {controlLabel}
            </text>
            <text x={plotR} y={height - 2} textAnchor="end" fill={CHART.case}>
              enriched in {caseLabel} →
            </text>
          </g>
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{termLabel(hover.t.term)}</div>
          <div className="num text-ink-2">
            NES {hover.t.nes > 0 ? "+" : "−"}
            {Math.abs(hover.t.nes).toFixed(2)} · FDR {fmtFdr(hover.t.fdr)} · {hover.t.size} genes
          </div>
          <div className="mt-0.5 text-ink-3">
            {selected === hover.t.term
              ? "Click to clear the volcano marks"
              : "Click to mark its genes on the volcano"}
          </div>
        </ChartTip>
      )}
      <div className="mt-3 flex flex-wrap items-center justify-between gap-x-6 gap-y-2 text-[12px] text-ink-2">
        <span className="inline-flex items-center gap-2">
          <span className="text-ink-3">genes in set</span>
          {[sMin, Math.round((sMin + sMax) / 2), sMax]
            .filter((v, i, a) => a.indexOf(v) === i)
            .map((v) => (
              <span key={v} className="inline-flex items-center gap-1">
                <svg width={rowH} height={rowH} aria-hidden>
                  <circle
                    cx={rowH / 2}
                    cy={rowH / 2}
                    r={r(v)}
                    fill="none"
                    stroke={CHART.ink2}
                    strokeWidth={1}
                  />
                </svg>
                <span className="num">{v}</span>
              </span>
            ))}
        </span>
        <span className="inline-flex items-center gap-2">
          <span className="text-ink-3">FDR</span>
          <span className="num">1</span>
          <span
            className="inline-block h-2.5 w-20 rounded-sm"
            style={{
              background: `linear-gradient(to right, ${fdrColor(1)}, ${fdrColor(0.1)}, ${fdrColor(0.01)}, ${fdrColor(0.001)})`,
            }}
          />
          <span className="num">≤0.001</span>
        </span>
      </div>
    </div>
  );
}

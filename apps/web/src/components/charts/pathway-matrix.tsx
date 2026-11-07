import { useState } from "react";
import type { PathwayMeta, PathwaySynthesis } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtNum } from "@/lib/format";
import { CHART, Legend, useMeasure } from "./common";
import { termLabel } from "./enrichment-bars";

const NES_CAP = 3;
const MAX_LOG_FDR = 3; // FDR 0.001 is as big as a bubble gets

function nesColor(v: number): string {
  const t = Math.max(-1, Math.min(1, v / NES_CAP));
  const pct = Math.round(25 + Math.abs(t) * 70);
  return t >= 0
    ? `color-mix(in oklab, var(--case) ${pct}%, var(--surface))`
    : `color-mix(in oklab, var(--control) ${pct}%, var(--surface))`;
}

/** Pathways (rows) by datasets (columns). Each bubble is one GSEA result: colour is the
 * direction and strength (NES), size is how sure it is (FDR). A row of same-coloured bubbles
 * is the same biology found independently by every lab. */
export function PathwayMatrix({
  pathways,
  n = 20,
  fdrThreshold,
}: {
  pathways: PathwaySynthesis;
  n?: number;
  fdrThreshold?: number;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ t: PathwayMeta; m: string; x: number; y: number } | null>(
    null,
  );
  const members = pathways.members ?? [];
  const fdrT = fdrThreshold ?? pathways.fdr_threshold;
  const terms = [...pathways.terms]
    .sort(
      (a, b) =>
        b.consistency - a.consistency ||
        b.n_sig_fdr - a.n_sig_fdr ||
        Math.abs(b.mean_nes) - Math.abs(a.mean_nes),
    )
    .slice(0, n);
  const labelW = Math.min(210, Math.max(120, width * 0.38));
  const headH = 64;
  const rowH = 26;
  const sigW = 56; // the "sig." count column on the right
  const colW = members.length ? (width - labelW - sigW) / members.length : 0;
  const cell = Math.max(22, Math.min(44, colW));
  const gridW = cell * members.length;
  // every dataset stays visible: when the container is too narrow the chart scrolls sideways
  const svgW = Math.max(width, labelW + gridW + sigW);
  const height = headH + rowH * terms.length + 8;
  const rMax = Math.min(cell, rowH) / 2 - 2;
  const radius = (fdr: number | undefined) => {
    if (fdr === undefined) return 0;
    const s = Math.min(MAX_LOG_FDR, -Math.log10(Math.max(fdr, 1e-12))) / MAX_LOG_FDR;
    return 3 + s * (rMax - 3);
  };
  const short = (l: string) => l.split(":")[0];

  if (terms.length === 0 || members.length === 0)
    return <p className="text-sm text-ink-3">No pathway results to compare.</p>;

  return (
    <div ref={ref} className="relative w-full overflow-x-auto">
      {width > 0 && (
        <svg
          width={svgW}
          height={height}
          role="img"
          aria-label={`Pathway enrichment across ${members.length} datasets for ${terms.length} sets`}
        >
          {members.map((m, j) => (
            <text
              key={m}
              transform={`translate(${labelW + j * cell + cell / 2},${headH - 10}) rotate(-45)`}
              fontSize={11}
              fill={CHART.ink2}
              fontFamily="var(--font-mono)"
            >
              {short(m)}
            </text>
          ))}
          {terms.map((t, i) => {
            const y = headH + i * rowH + rowH / 2;
            const consistent = t.consistency >= 1 && t.n_members >= 2;
            return (
              <g key={t.term}>
                {i % 2 === 0 && (
                  <rect
                    x={0}
                    y={y - rowH / 2}
                    width={labelW + gridW + 48}
                    height={rowH}
                    fill="var(--surface-2)"
                    opacity={0.5}
                  />
                )}
                <text
                  x={labelW - 10}
                  y={y}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={12}
                  fill={consistent ? CHART.ink : CHART.ink2}
                  fontWeight={consistent ? 600 : 400}
                >
                  {termLabel(t.term)}
                </text>
                {members.map((m, j) => {
                  const v = t.nes?.[m];
                  const cx = labelW + j * cell + cell / 2;
                  if (v === undefined)
                    return (
                      <text
                        key={m}
                        x={cx}
                        y={y}
                        dy="0.32em"
                        textAnchor="middle"
                        fontSize={11}
                        fill={CHART.ink3}
                      >
                        ×
                      </text>
                    );
                  const fdr = t.fdr?.[m];
                  const sig = fdr !== undefined && fdr < fdrT;
                  return (
                    <g
                      key={m}
                      role="graphics-symbol"
                      aria-label={`${termLabel(t.term)} in ${short(m)}: NES ${fmtNum(v)}`}
                      onMouseMove={(e) => {
                        const rect = (
                          e.currentTarget.ownerSVGElement as SVGSVGElement
                        ).getBoundingClientRect();
                        setHover({ t, m, x: e.clientX - rect.left, y: e.clientY - rect.top });
                      }}
                      onMouseLeave={() => setHover(null)}
                    >
                      <rect
                        x={cx - cell / 2}
                        y={y - rowH / 2}
                        width={cell}
                        height={rowH}
                        fill="transparent"
                      />
                      <circle
                        cx={cx}
                        cy={y}
                        r={radius(fdr ?? 1)}
                        fill={nesColor(v)}
                        stroke={sig ? (v > 0 ? CHART.case : CHART.control) : CHART.surface}
                        strokeWidth={sig ? 1.5 : 1}
                        opacity={sig ? 1 : 0.55}
                      />
                    </g>
                  );
                })}
                <text
                  x={labelW + gridW + 12}
                  y={y}
                  dy="0.32em"
                  fontSize={11}
                  fill={consistent ? CHART.ink : CHART.ink3}
                  className="num"
                >
                  {t.n_sig_fdr}/{t.n_members}
                </text>
              </g>
            );
          })}
          <text
            x={labelW + gridW + 12}
            y={headH - 10}
            fontSize={11}
            fill={CHART.ink3}
            className="num"
          >
            sig.
          </text>
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{termLabel(hover.t.term)}</div>
          <div className="accession text-ink-2">
            {hover.m.replace(/:/, " · ").replaceAll("_", " ")}
          </div>
          <div className="num text-ink-2">
            NES {fmtNum(hover.t.nes?.[hover.m])} · FDR{" "}
            {hover.t.fdr?.[hover.m] === undefined ? "n/a" : fmtNum(hover.t.fdr[hover.m], 3)}
          </div>
          <div className="num text-ink-3">
            same direction in {Math.round(hover.t.consistency * 100)}% of {hover.t.n_members}{" "}
            datasets
          </div>
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-2">
        <Legend
          items={[
            { label: "higher in case", color: CHART.case },
            { label: "higher in control", color: CHART.control },
          ]}
        />
        <span className="inline-flex items-center gap-2">
          <span className="inline-flex items-end gap-0.5" aria-hidden>
            <span className="inline-block h-1.5 w-1.5 rounded-full bg-ink-3" />
            <span className="inline-block h-2.5 w-2.5 rounded-full bg-ink-3" />
            <span className="inline-block h-3.5 w-3.5 rounded-full bg-ink-3" />
          </span>
          bigger = smaller FDR; ringed = FDR &lt; {fdrT}; × = not tested
        </span>
      </div>
    </div>
  );
}

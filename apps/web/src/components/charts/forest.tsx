import { scaleLinear, scaleSqrt } from "d3-scale";
import { useState } from "react";
import type { GeneLookupAcross } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtLfc, fmtP } from "@/lib/format";
import { AxisBottom, CHART, useMeasure } from "./common";

/** One gene across datasets: a point ± 1.96·SE per member and the pooled estimate as a
 * diamond. Points are sized by the samples behind them, so a big study reads as a big dot.
 * ``size="hero"`` is the full-width version for the gene the question asked about. */
export function Forest({
  lookup,
  members,
  size = "normal",
}: {
  lookup: GeneLookupAcross;
  members: string[];
  size?: "normal" | "hero";
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ label: string; x: number; y: number } | null>(null);
  const hero = size === "hero";
  const rowH = hero ? 30 : 24;
  const m = { top: 6, right: 16, bottom: 40, left: hero ? 190 : 150 };
  const labelW = Math.min(m.left, Math.max(90, width * 0.32));
  const rows = members.map((lab) => ({ label: lab, e: lookup.effects?.[lab] }));
  const meta = lookup.meta;
  const sizes = rows.map((r) => r.e?.n_samples ?? 0).filter((n) => n > 0);
  const dotR = scaleSqrt()
    .domain([Math.max(1, Math.min(...sizes, 1e9)), Math.max(2, ...sizes)])
    .range(hero ? [4.5, 11] : [3.5, 7]);
  const radius = (n: number | null | undefined) => (n ? dotR(n) : hero ? 6 : 4.5);
  const dia = hero ? 10 : 7;
  const height = m.top + m.bottom + (rows.length + (meta?.pooled_log2fc != null ? 1 : 0)) * rowH;
  let lo = -1;
  let hi = 1;
  for (const r of rows) {
    if (r.e?.log2fc != null) {
      const se = r.e.se ?? 0;
      lo = Math.min(lo, r.e.log2fc - 1.96 * se);
      hi = Math.max(hi, r.e.log2fc + 1.96 * se);
    }
  }
  if (meta?.ci_low != null) lo = Math.min(lo, meta.ci_low);
  if (meta?.ci_high != null) hi = Math.max(hi, meta.ci_high);
  const x = scaleLinear()
    .domain([lo, hi])
    .range([labelW, width - m.right])
    .nice();
  const short = (l: string) => l.replace(/:/, " · ").replaceAll("_", " ");

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Forest plot for ${lookup.symbol ?? lookup.query}`}
        >
          <line x1={x(0)} x2={x(0)} y1={m.top} y2={height - m.bottom} stroke={CHART.ink2} />
          {rows.map((r, i) => {
            const y = m.top + i * rowH + rowH / 2;
            const v = r.e?.log2fc;
            return (
              <g
                key={r.label}
                role="graphics-symbol"
                aria-label={`${short(r.label)}: log2FC ${v == null ? "not tested" : fmtLfc(v)}`}
                onMouseMove={(e) => {
                  const rect = (
                    e.currentTarget.ownerSVGElement as SVGSVGElement
                  ).getBoundingClientRect();
                  setHover({ label: r.label, x: e.clientX - rect.left, y: e.clientY - rect.top });
                }}
                onMouseLeave={() => setHover(null)}
              >
                <rect x={0} y={y - rowH / 2} width={width} height={rowH} fill="transparent" />
                <text
                  x={labelW - 8}
                  y={y}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={hero ? 12 : 11}
                  fill={CHART.ink2}
                  fontFamily="var(--font-mono)"
                >
                  {r.label.split(":")[0]}
                </text>
                {v == null ? (
                  <text
                    x={x(0)}
                    y={y}
                    dy="0.32em"
                    textAnchor="middle"
                    fontSize={11}
                    fill={CHART.ink3}
                  >
                    ×
                  </text>
                ) : (
                  <>
                    <line
                      x1={x(v - 1.96 * (r.e?.se ?? 0))}
                      x2={x(v + 1.96 * (r.e?.se ?? 0))}
                      y1={y}
                      y2={y}
                      stroke={v > 0 ? CHART.case : CHART.control}
                      strokeWidth={hero ? 2 : 1.5}
                    />
                    <circle
                      cx={x(v)}
                      cy={y}
                      r={radius(r.e?.n_samples)}
                      fill={v > 0 ? CHART.case : CHART.control}
                      stroke={CHART.surface}
                      strokeWidth={1.2}
                    />
                  </>
                )}
              </g>
            );
          })}
          {meta?.pooled_log2fc != null && (
            <g>
              {(() => {
                const y = m.top + rows.length * rowH + rowH / 2;
                const p = meta.pooled_log2fc;
                const l = meta.ci_low ?? p;
                const h = meta.ci_high ?? p;
                return (
                  <>
                    <line
                      x1={labelW}
                      x2={width - m.right}
                      y1={y - rowH / 2}
                      y2={y - rowH / 2}
                      stroke={CHART.grid}
                    />
                    <text
                      x={labelW - 8}
                      y={y}
                      dy="0.32em"
                      textAnchor="end"
                      fontSize={hero ? 12 : 11}
                      fontWeight={600}
                      fill={CHART.ink}
                    >
                      pooled
                    </text>
                    <polygon
                      points={`${x(l)},${y} ${x(p)},${y - dia} ${x(h)},${y} ${x(p)},${y + dia}`}
                      fill={CHART.ink}
                    />
                  </>
                );
              })()}
            </g>
          )}
          <AxisBottom
            scale={x}
            y={height - m.bottom + 4}
            width={width}
            label="log2 fold change (95% CI)"
            format={(v) => fmtLfc(v).replace(".00", "")}
          />
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{short(hover.label)}</div>
          {(() => {
            const e = lookup.effects?.[hover.label];
            if (!e || e.log2fc == null)
              return <div className="text-ink-3">not tested in this dataset</div>;
            return (
              <div className="text-ink-2">
                log2FC {fmtLfc(e.log2fc)} · SE {e.se?.toFixed(2)} · padj {fmtP(e.padj)} ·{" "}
                {lookup.per_member?.[hover.label]?.replaceAll("_", " ")}
                {e.n_samples ? ` · ${e.n_samples} samples` : ""}
              </div>
            );
          })()}
        </ChartTip>
      )}
    </div>
  );
}

import { scaleLinear } from "d3-scale";
import { useMemo, useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtInt, fmtNum } from "@/lib/format";
import { type GseaTable, runningScore } from "@/lib/gsea";
import { cn } from "@/lib/utils";
import { CHART, useMeasure } from "./common";

/** Pick one point per pixel column from a dense series: the extreme in each bucket, so the
 * peak survives downsampling. */
function thin(values: Float64Array, px: number): { i: number; v: number }[] {
  const n = values.length;
  if (n <= px) return Array.from(values, (v, i) => ({ i, v }));
  const out: { i: number; v: number }[] = [];
  for (let b = 0; b < px; b++) {
    const lo = Math.floor((b * n) / px);
    const hi = Math.max(lo + 1, Math.floor(((b + 1) * n) / px));
    let best = lo;
    for (let i = lo + 1; i < hi; i++) if (Math.abs(values[i]) > Math.abs(values[best])) best = i;
    out.push({ i: best, v: values[best] });
  }
  return out;
}

/** The classic GSEA enrichment plot, three bands over one rank axis: the running score with
 * its peak marked, a barcode of where the set's genes fall, and the ranking metric. */
export function GseaPlot({
  table,
  term,
  caseLabel,
  controlLabel,
}: {
  table: GseaTable;
  term: string;
  caseLabel: string;
  controlLabel: string;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ rank: number; x: number; y: number } | null>(null);
  const hits = table.terms[term]?.hits ?? [];
  const run = useMemo(() => runningScore(table, hits), [table, hits]);
  const leading = useMemo(() => new Set(run.leading), [run]);

  const padL = 44;
  const padR = 12;
  const esH = 150;
  const barH = 34;
  const metH = 64;
  const gap = 8;
  const top = 6;
  const yBar = top + esH + gap;
  const yMet = yBar + barH + gap;
  const plotW = Math.max(0, width - padL - padR);
  // The two direction labels share a row when they fit, else the control one drops a row.
  const caseText = `← higher in ${caseLabel}`;
  const controlText = `higher in ${controlLabel} →`;
  const approxW = (t: string) => t.length * 6.4; // 11px semibold
  const stacked = approxW(caseText) + approxW(controlText) + 24 > plotW;
  const axisH = stacked ? 50 : 36;
  const height = yMet + metH + axisH;
  const x = scaleLinear()
    .domain([0, table.n - 1])
    .range([padL, padL + plotW]);

  const esMax = Math.max(0.1, Math.abs(run.es)) * 1.1;
  const yEs = scaleLinear()
    .domain([-esMax, esMax])
    .range([top + esH, top]);
  const mAbs = Math.max(
    1,
    Math.abs(table.metric[0] ?? 0),
    Math.abs(table.metric[table.n - 1] ?? 0),
  );
  const yM = scaleLinear()
    .domain([-mAbs, mAbs])
    .range([yMet + metH, yMet]);

  const curve = useMemo(() => thin(run.res, Math.max(1, Math.floor(plotW))), [run, plotW]);
  const metric = useMemo(() => thin(table.metric, Math.max(1, Math.floor(plotW))), [table, plotW]);
  const esPath = curve
    .map((p, k) => `${k ? "L" : "M"}${x(p.i).toFixed(1)},${yEs(p.v).toFixed(1)}`)
    .join("");
  const esArea = `${esPath}L${x(curve[curve.length - 1]?.i ?? 0).toFixed(1)},${yEs(0)}L${x(0).toFixed(1)},${yEs(0)}Z`;
  const metArea = `M${x(0)},${yM(0)}${metric.map((p) => `L${x(p.i).toFixed(1)},${yM(p.v).toFixed(1)}`).join("")}L${x(table.n - 1)},${yM(0)}Z`;

  // nearest hit to the cursor, for the tooltip
  const nearestHit = (rank: number) => {
    let best = -1;
    for (const h of hits) if (best < 0 || Math.abs(h - rank) < Math.abs(best - rank)) best = h;
    return best;
  };
  const locate = (e: React.MouseEvent<SVGSVGElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    if (px < padL || px > padL + plotW) return setHover(null);
    const rank = Math.round(x.invert(px));
    setHover({ rank, x: px, y: e.clientY - rect.top });
  };

  if (hits.length === 0) {
    return (
      <p className="text-[13px] text-ink-3">
        This run has no stored positions for the set, so the curve cannot be drawn.
      </p>
    );
  }
  const hRank = hover ? nearestHit(hover.rank) : -1;
  const hSymbol = hRank >= 0 ? table.ranked[hRank] : null;
  const esColor = run.es >= 0 ? CHART.case : CHART.control;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label={`Enrichment plot: running score peaks at ${fmtNum(run.es, 2)} at rank ${fmtInt(run.peak + 1)} of ${fmtInt(table.n)}; ${hits.length} genes in the set`}
          onMouseMove={locate}
          onMouseLeave={() => setHover(null)}
        >
          {/* running score */}
          <g fontSize={10} fill={CHART.ink3}>
            {[-esMax, 0, esMax].map((v) => (
              <g key={v}>
                <line x1={padL} x2={padL + plotW} y1={yEs(v)} y2={yEs(v)} stroke={CHART.grid} />
                <text x={padL - 6} y={yEs(v)} dy="0.32em" textAnchor="end" className="num">
                  {fmtNum(v, 1)}
                </text>
              </g>
            ))}
            <text
              transform={`translate(${12},${top + esH / 2}) rotate(-90)`}
              textAnchor="middle"
              fontSize={11}
              fill={CHART.ink2}
            >
              running score
            </text>
          </g>
          <path d={esArea} fill={esColor} fillOpacity={0.12} />
          <path d={esPath} fill="none" stroke={esColor} strokeWidth={1.8} />
          <line
            x1={x(run.peak)}
            x2={x(run.peak)}
            y1={yEs(run.es)}
            y2={yMet + metH}
            stroke={CHART.ink3}
            strokeDasharray="3 3"
          />
          <circle
            cx={x(run.peak)}
            cy={yEs(run.es)}
            r={3.5}
            fill={esColor}
            stroke={CHART.surface}
            strokeWidth={1.5}
          />
          <text
            x={x(run.peak) + (run.es >= 0 ? 8 : -8)}
            y={yEs(run.es)}
            dy={run.es >= 0 ? "-0.4em" : "1.1em"}
            textAnchor={run.es >= 0 ? "start" : "end"}
            fontSize={11}
            fontWeight={600}
            fill={CHART.ink}
            className="num"
          >
            ES {fmtNum(run.es, 2)}
          </text>

          {/* barcode */}
          <rect
            x={padL}
            y={yBar}
            width={plotW}
            height={barH}
            fill={CHART.surface}
            stroke={CHART.grid}
          />
          {hits.map((h) => (
            <line
              key={h}
              x1={x(h)}
              x2={x(h)}
              y1={yBar + 2}
              y2={yBar + barH - 2}
              stroke={leading.has(h) ? esColor : CHART.ink3}
              strokeWidth={plotW / table.n > 1.2 ? 1.4 : 1}
              opacity={leading.has(h) ? 1 : 0.55}
            />
          ))}

          {/* ranked metric */}
          <path d={metArea} fill={CHART.ink3} fillOpacity={0.35} />
          <line x1={padL} x2={padL + plotW} y1={yM(0)} y2={yM(0)} stroke={CHART.grid} />
          <text
            transform={`translate(${12},${yMet + metH / 2}) rotate(-90)`}
            textAnchor="middle"
            fontSize={11}
            fill={CHART.ink2}
          >
            rank metric
          </text>
          <line
            x1={x(table.zeroCross)}
            x2={x(table.zeroCross)}
            y1={yMet}
            y2={yMet + metH}
            stroke={CHART.ink3}
            strokeDasharray="2 3"
          />
          <text
            x={x(table.zeroCross)}
            y={yMet + metH + 12}
            textAnchor="middle"
            fontSize={10}
            fill={CHART.ink3}
            className="num"
          >
            zero at {fmtInt(table.zeroCross)}
          </text>

          {/* rank axis */}
          <g fontSize={11} fontWeight={600}>
            <text x={padL} y={height - (stacked ? 18 : 4)} fill={CHART.case}>
              {caseText}
            </text>
            <text x={padL + plotW} y={height - 4} textAnchor="end" fill={CHART.control}>
              {controlText}
            </text>
          </g>

          {hover && (
            <line
              x1={x(hover.rank)}
              x2={x(hover.rank)}
              y1={top}
              y2={yMet + metH}
              stroke={CHART.ink}
              strokeOpacity={0.4}
            />
          )}
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="num text-ink-2">
            rank {fmtInt(hover.rank + 1)} · score {fmtNum(run.res[hover.rank], 2)}
          </div>
          {hSymbol && (
            <div
              className={cn("mt-0.5", Math.abs(hRank - hover.rank) > table.n / 100 && "text-ink-3")}
            >
              nearest set gene <span className="font-mono font-medium text-ink">{hSymbol}</span>{" "}
              <span className="num">at rank {fmtInt(hRank + 1)}</span>
              {leading.has(hRank) && <span className="text-ink-3"> · leading edge</span>}
            </div>
          )}
        </ChartTip>
      )}
    </div>
  );
}

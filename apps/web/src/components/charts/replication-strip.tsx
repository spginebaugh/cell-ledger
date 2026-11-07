import { useState } from "react";
import type { GeneMeta } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtLfc, fmtP } from "@/lib/format";
import { CHART, Legend, useMeasure } from "./common";

const LFC_CAP = 3;
const MIN_CELL = 18;
const POOLED_GAP = 10;
const RIGHT_PAD = 44; // the rotated "pooled" header overhangs its column

/** Whether a comparison report carries each dataset's own estimate for its top genes.
 * Reports written before that field existed do not; the strip then has nothing honest to draw. */
export function hasPerMemberEffects(rows: GeneMeta[]): boolean {
  return rows.length > 0 && rows.every((g) => g.effects && Object.keys(g.effects).length > 0);
}

function lfcColor(v: number): string {
  const t = Math.max(-1, Math.min(1, v / LFC_CAP));
  const pct = Math.round(20 + Math.abs(t) * 75);
  return t >= 0
    ? `color-mix(in oklab, var(--case) ${pct}%, var(--surface))`
    : `color-mix(in oklab, var(--control) ${pct}%, var(--surface))`;
}

/** The robust genes (rows) in every dataset (columns). Cell colour is that dataset's own
 * fold change; a solid cell is significant there, a faint one is not; × means untested.
 * The last column is the pooled estimate. Reading across a row: "this gene goes up in
 * seven of eight studies". */
export function ReplicationStrip({
  rows,
  members,
  alpha,
  n = 15,
  onSelect,
}: {
  rows: GeneMeta[];
  members: string[];
  alpha: number;
  n?: number;
  onSelect?: (symbol: string) => void;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{
    g: GeneMeta;
    m: string | null;
    x: number;
    y: number;
  } | null>(null);
  const shown = rows.slice(0, n);
  const labelW = Math.min(110, Math.max(72, width * 0.22));
  const headH = 60;
  const rowH = 22;
  const cols = members.length + 1; // + pooled
  const avail = width - labelW - POOLED_GAP - RIGHT_PAD;
  const cell = Math.max(MIN_CELL, Math.min(40, avail / cols));
  // every column stays visible: when the container is too narrow the chart scrolls sideways
  const svgW = Math.max(width, labelW + cols * cell + POOLED_GAP + RIGHT_PAD);
  const gap = 2;
  const pooledX = labelW + members.length * cell + POOLED_GAP;
  const height = headH + rowH * shown.length;
  const short = (l: string) => l.split(":")[0];

  if (shown.length === 0 || !hasPerMemberEffects(shown)) return null;

  return (
    <div ref={ref} className="relative w-full overflow-x-auto">
      {width > 0 && (
        <svg
          width={svgW}
          height={height}
          role="img"
          aria-label={`${shown.length} robust genes across ${members.length} datasets`}
        >
          {members.map((m, j) => (
            <text
              key={m}
              transform={`translate(${labelW + j * cell + cell / 2},${headH - 8}) rotate(-45)`}
              fontSize={11}
              fill={CHART.ink2}
              fontFamily="var(--font-mono)"
            >
              {short(m)}
            </text>
          ))}
          <text
            transform={`translate(${pooledX + cell / 2},${headH - 8}) rotate(-45)`}
            fontSize={11}
            fontWeight={600}
            fill={CHART.ink}
          >
            pooled
          </text>
          {shown.map((g, i) => {
            const y = headH + i * rowH;
            const label = g.symbol ?? g.gene_id;
            return (
              <g key={g.gene_id}>
                <text
                  x={labelW - 8}
                  y={y + rowH / 2}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={12}
                  fontFamily="var(--font-mono)"
                  fontWeight={500}
                  fill={CHART.ink}
                  className={onSelect && g.symbol ? "cursor-pointer hover:underline" : undefined}
                  onClick={() => g.symbol && onSelect?.(g.symbol)}
                >
                  {label}
                </text>
                {members.map((m, j) => {
                  const e = g.effects?.[m];
                  const x = labelW + j * cell;
                  const v = e?.log2fc;
                  const sig = e?.padj != null && e.padj < alpha;
                  return (
                    <g
                      key={m}
                      role="graphics-symbol"
                      aria-label={`${label} in ${short(m)}: ${v == null ? "not tested" : fmtLfc(v)}`}
                      onMouseMove={(ev) => {
                        const rect = (
                          ev.currentTarget.ownerSVGElement as SVGSVGElement
                        ).getBoundingClientRect();
                        setHover({ g, m, x: ev.clientX - rect.left, y: ev.clientY - rect.top });
                      }}
                      onMouseLeave={() => setHover(null)}
                    >
                      {v == null ? (
                        <>
                          <rect
                            x={x + gap / 2}
                            y={y + gap / 2}
                            width={cell - gap}
                            height={rowH - gap}
                            rx={3}
                            fill="var(--surface-2)"
                          />
                          <text
                            x={x + cell / 2}
                            y={y + rowH / 2}
                            dy="0.32em"
                            textAnchor="middle"
                            fontSize={11}
                            fill={CHART.ink3}
                          >
                            ×
                          </text>
                        </>
                      ) : (
                        <rect
                          x={x + gap / 2}
                          y={y + gap / 2}
                          width={cell - gap}
                          height={rowH - gap}
                          rx={3}
                          fill={lfcColor(v)}
                          opacity={sig ? 1 : 0.35}
                          stroke={sig ? "transparent" : CHART.grid}
                        />
                      )}
                    </g>
                  );
                })}
                {/* pooled */}
                <g
                  role="graphics-symbol"
                  aria-label={`${label} pooled: ${fmtLfc(g.pooled_log2fc)}`}
                  onMouseMove={(ev) => {
                    const rect = (
                      ev.currentTarget.ownerSVGElement as SVGSVGElement
                    ).getBoundingClientRect();
                    setHover({ g, m: null, x: ev.clientX - rect.left, y: ev.clientY - rect.top });
                  }}
                  onMouseLeave={() => setHover(null)}
                >
                  <rect
                    x={pooledX + gap / 2}
                    y={y + gap / 2}
                    width={cell - gap}
                    height={rowH - gap}
                    rx={3}
                    fill={lfcColor(g.pooled_log2fc ?? 0)}
                    stroke={CHART.ink}
                    strokeWidth={1}
                  />
                </g>
              </g>
            );
          })}
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{hover.g.symbol ?? hover.g.gene_id}</div>
          {hover.m === null ? (
            <div className="num text-ink-2">
              pooled log2FC {fmtLfc(hover.g.pooled_log2fc)} · padj {fmtP(hover.g.padj)} ·{" "}
              significant in {hover.g.n_sig} of {hover.g.n_tested}
            </div>
          ) : (
            (() => {
              const e = hover.g.effects?.[hover.m];
              return (
                <>
                  <div className="accession text-ink-2">
                    {hover.m.replace(/:/, " · ").replaceAll("_", " ")}
                  </div>
                  {e?.log2fc == null ? (
                    <div className="text-ink-3">not tested in this dataset</div>
                  ) : (
                    <div className="num text-ink-2">
                      log2FC {fmtLfc(e.log2fc)} · padj {fmtP(e.padj)}
                      {e.n_samples != null && <> · {e.n_samples} samples</>}
                    </div>
                  )}
                </>
              );
            })()
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-2">
        <Legend
          items={[
            { label: "higher in case", color: CHART.case },
            { label: "higher in control", color: CHART.control },
          ]}
        />
        <span>solid = padj &lt; {alpha} there; faint = not significant; × = not tested</span>
      </div>
    </div>
  );
}

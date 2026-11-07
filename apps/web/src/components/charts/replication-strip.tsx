import { useState } from "react";
import type { GeneMeta } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtLfc, fmtP } from "@/lib/format";
import { CHART, useMeasure } from "./common";

const MIN_CELL = 18;
const POOLED_GAP = 10;
const RIGHT_PAD = 44; // the rotated "pooled" header overhangs its column

/** Whether a comparison report carries each dataset's own estimate for its top genes.
 * Reports written before that field existed do not; the strip then has nothing honest to draw. */
export function hasPerMemberEffects(rows: GeneMeta[]): boolean {
  return rows.length > 0 && rows.every((g) => g.effects && Object.keys(g.effects).length > 0);
}

const RAMP_LO = 12; // % of the arm colour at a fold change of 0
const RAMP_HI = 96; // % at the cap

function mix(arm: "case" | "control", pct: number): string {
  return `color-mix(in oklab, var(--${arm}) ${pct}%, var(--surface))`;
}

/** Colour for one dataset's fold change: the arm hue for its sign, saturation for its size,
 * on a ramp that saturates at ``cap``. */
function lfcColor(v: number, cap: number): string {
  const t = Math.min(1, Math.abs(v) / cap);
  const pct = Math.round(RAMP_LO + t * (RAMP_HI - RAMP_LO));
  return mix(v >= 0 ? "case" : "control", pct);
}

/** Where the ramp saturates: the 90th percentile of the fold changes on show, so the strip
 * uses its whole range whether the genes move 2-fold or 200-fold. Never below 1. */
export function colorCap(rows: GeneMeta[], members: string[]): number {
  const mags: number[] = [];
  for (const g of rows) {
    if (g.pooled_log2fc != null) mags.push(Math.abs(g.pooled_log2fc));
    for (const m of members) {
      const v = g.effects?.[m]?.log2fc;
      if (v != null) mags.push(Math.abs(v));
    }
  }
  if (mags.length === 0) return 1;
  mags.sort((a, b) => a - b);
  const q = mags[Math.min(mags.length - 1, Math.floor(mags.length * 0.9))];
  return Math.max(1, Math.ceil(q * 2) / 2);
}

/** The robust genes (rows) in every dataset (columns). Cell colour is that dataset's own
 * fold change, deeper for a bigger change and in the other arm's colour when that dataset went
 * the other way; a solid cell is significant there, a faint one is not; × means untested.
 * The last column is the pooled estimate. Reading across a row: "this gene goes up in
 * seven of eight studies". ``tone`` is the direction the strip holds, for its legend. */
export function ReplicationStrip({
  rows,
  members,
  alpha,
  tone = "case",
  n = 15,
  onSelect,
}: {
  rows: GeneMeta[];
  members: string[];
  alpha: number;
  /** which direction these genes move; the legend ramp takes that colour */
  tone?: "case" | "control";
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
  const cap = colorCap(shown, members);
  const other: "case" | "control" = tone === "case" ? "control" : "case";
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
                          fill={lfcColor(v, cap)}
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
                    fill={lfcColor(g.pooled_log2fc ?? 0, cap)}
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
      <div className="mt-2 flex flex-wrap items-center justify-between gap-x-4 gap-y-1 text-[12px] text-ink-2">
        <span className="inline-flex items-center gap-2">
          <span className="num">0</span>
          <span
            aria-hidden
            className="inline-block h-2.5 w-16 rounded-sm"
            style={{
              background: `linear-gradient(to right, ${mix(tone, RAMP_LO)}, ${mix(tone, RAMP_HI)})`,
            }}
          />
          <span className="num">≥ {cap.toFixed(1)}</span>
          <span className="text-ink-3">log2FC in that dataset</span>
          <span
            aria-hidden
            className="ml-2 inline-block h-2.5 w-2.5 rounded-sm"
            style={{ background: mix(other, 70) }}
          />
          <span className="text-ink-3">went the other way</span>
        </span>
        <span className="text-ink-3">
          solid = padj &lt; {alpha} there · faint = not significant · × = not tested
        </span>
      </div>
    </div>
  );
}

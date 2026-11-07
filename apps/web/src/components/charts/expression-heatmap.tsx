import { useEffect, useMemo, useRef, useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtLfc, fmtNum, fmtP } from "@/lib/format";
import { armPurity, type HeatmapTable } from "@/lib/heatmap";
import { cssVar } from "@/lib/theme";
import { armColor, CHART, Legend, useMeasure } from "./common";

const Z_CAP = 2.5;

/** Blend two CSS colours in OKLab, as the concordance heatmap does, for a diverging ramp. */
function mix(hi: string, lo: string, surface: string, t: number): string {
  const c = Math.max(-1, Math.min(1, t / Z_CAP));
  const pct = Math.round(Math.abs(c) * 90);
  return c >= 0
    ? `color-mix(in oklab, ${hi} ${pct}%, ${surface})`
    : `color-mix(in oklab, ${lo} ${pct}%, ${surface})`;
}

/** The classic genomics heatmap: top DE genes (rows) by samples (columns), each gene z-scored
 * across the samples, both axes ordered by hierarchical clustering. The genes were picked by
 * the contrast, so a split between arms is expected; the picture is about per-sample
 * consistency (does every sample follow the pattern?), not independent evidence of a difference. */
export function ExpressionHeatmap({
  table,
  caseLabel,
  controlLabel,
  selected = null,
  onSelect,
  themeKey,
}: {
  table: HeatmapTable;
  caseLabel: string;
  controlLabel: string;
  selected?: string | null;
  onSelect?: (symbol: string, geneId: string) => void;
  themeKey?: string;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<{ gi: number; si: number; x: number; y: number } | null>(null);
  const labelW = Math.min(96, Math.max(64, width * 0.18));
  const barH = 10;
  const top = barH + 6;
  const rowH = Math.max(7, Math.min(14, Math.floor(470 / Math.max(1, table.nGenes))));
  const plotW = Math.max(0, width - labelW);
  const colW = plotW / Math.max(1, table.nSamples);
  const height = top + table.nGenes * rowH;
  const purity = useMemo(() => armPurity(table), [table]);

  // Where each arm's run of columns sits, for the bar and its labels.
  const runs = useMemo(() => {
    const out: { arm: string; from: number; to: number }[] = [];
    table.colOrder.forEach((si, k) => {
      const arm = table.samples[si].arm;
      const last = out[out.length - 1];
      if (last && last.arm === arm) last.to = k + 1;
      else out.push({ arm, from: k, to: k + 1 });
    });
    return out;
  }, [table]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: themeKey forces a redraw when the CSS variables change
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = plotW * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, plotW, height);
    // z scores use their own diverging pair so cell colour is never read as "case" or "control"
    const hi = cssVar("--z-hi") || "#7b3294";
    const lo = cssVar("--z-lo") || "#1b8a4a";
    const caseC = cssVar("--case") || "#2b6fc8";
    const controlC = cssVar("--control") || "#d3602a";
    const surface = cssVar("--surface") || "#ffffff";
    // columns: 1px cells need no gap; wide cells get a surface hairline between them
    const gap = colW >= 4 ? 1 : 0;
    table.rowOrder.forEach((gi, r) => {
      const row = table.z[gi];
      table.colOrder.forEach((si, c) => {
        ctx.fillStyle = mix(hi, lo, surface, row[si]);
        ctx.fillRect(c * colW, top + r * rowH, Math.max(0.5, colW - gap), rowH - 1);
      });
    });
    // arm bar
    for (const run of runs) {
      ctx.fillStyle =
        run.arm === "case" ? caseC : run.arm === "control" ? controlC : cssVar("--muted");
      ctx.fillRect(run.from * colW, 0, (run.to - run.from) * colW - gap, barH);
    }
  }, [table, width, plotW, colW, rowH, height, runs, themeKey]);

  const locate = (e: React.MouseEvent) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const c = Math.floor(px / colW);
    const r = Math.floor((py - top) / rowH);
    if (c < 0 || c >= table.nSamples || r < 0 || r >= table.nGenes) return null;
    return { gi: table.rowOrder[r], si: table.colOrder[c], x: px + labelW, y: py };
  };

  const geneLabel = (gi: number) => table.genes[gi].symbol ?? table.genes[gi].gene_id;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <div className="relative" style={{ height }}>
          <svg
            width={labelW}
            height={height}
            className="absolute left-0 top-0"
            aria-hidden
            fontFamily="var(--font-mono)"
          >
            {table.rowOrder.map((gi, r) => {
              const g = table.genes[gi];
              const label = geneLabel(gi);
              const isSel = selected != null && label.toUpperCase() === selected.toUpperCase();
              const show = rowH >= 9 || r % 2 === 0;
              if (!show) return null;
              return (
                <text
                  key={g.gene_id}
                  x={labelW - 6}
                  y={top + r * rowH + rowH / 2}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={Math.min(11, rowH + 1)}
                  fill={isSel ? "var(--accent-ink)" : g.log2fc > 0 ? CHART.case : CHART.control}
                  fontWeight={isSel ? 700 : 500}
                  className={onSelect && g.symbol ? "cursor-pointer hover:underline" : undefined}
                  onClick={() => g.symbol && onSelect?.(g.symbol, g.gene_id)}
                >
                  {label}
                </text>
              );
            })}
          </svg>
          <canvas
            ref={canvasRef}
            style={{ width: plotW, height, left: labelW }}
            className="absolute top-0 block cursor-crosshair"
            role="img"
            aria-label={`Expression heatmap: ${table.nGenes} genes across ${table.nSamples} samples, both clustered`}
            onMouseMove={(e) => setHover(locate(e))}
            onMouseLeave={() => setHover(null)}
            onClick={(e) => {
              const h = locate(e);
              const g = h && table.genes[h.gi];
              if (g?.symbol) onSelect?.(g.symbol, g.gene_id);
            }}
          />
          {hover && (
            <>
              <div
                aria-hidden
                className="pointer-events-none absolute border border-ink"
                style={{
                  left: labelW + table.colOrder.indexOf(hover.si) * colW - 1,
                  top: top + table.rowOrder.indexOf(hover.gi) * rowH - 1,
                  width: colW + 1,
                  height: rowH + 1,
                }}
              />
              <div
                aria-hidden
                className="pointer-events-none absolute border-l border-r border-ink/40"
                style={{
                  left: labelW + table.colOrder.indexOf(hover.si) * colW - 1,
                  top: 0,
                  width: colW + 1,
                  height,
                }}
              />
            </>
          )}
        </div>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{geneLabel(hover.gi)}</div>
          <div className="text-ink-2">
            log2FC {fmtLfc(table.genes[hover.gi].log2fc)} · padj {fmtP(table.genes[hover.gi].padj)}
          </div>
          <div className="mt-1 accession">{table.samples[hover.si].id}</div>
          <div className="text-ink-2">
            <span className="font-medium" style={{ color: armColor(table.samples[hover.si].arm) }}>
              {table.samples[hover.si].arm === "case" ? caseLabel : controlLabel}
            </span>
            <span className="num">
              {" "}
              · z {fmtNum(table.z[hover.gi][hover.si], 1)} · log2{" "}
              {fmtNum(table.log2[hover.gi][hover.si], 1)}
            </span>
          </div>
          {onSelect && table.genes[hover.gi].symbol && (
            <div className="mt-0.5 text-ink-3">Click to open the gene</div>
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-[12px] text-ink-2">
          <Legend
            items={[
              { label: caseLabel, color: CHART.case },
              { label: controlLabel, color: CHART.control },
            ]}
          />
          <span className="inline-flex items-center gap-1.5">
            <span
              className="inline-block h-2.5 w-16 rounded-sm"
              style={{
                background: `linear-gradient(to right, ${mix("var(--z-hi)", "var(--z-lo)", "var(--surface)", -Z_CAP)}, var(--surface), ${mix("var(--z-hi)", "var(--z-lo)", "var(--surface)", Z_CAP)})`,
              }}
            />
            cell: below → above the gene's average (z, ±{Z_CAP})
          </span>
        </div>
        {purity != null && table.nSamples >= 6 && (
          <span
            className="num text-[12px] text-ink-3"
            title="Share of neighbouring samples, in clustered order, that share an arm: how cleanly individual samples follow the group pattern for these genes. The genes were chosen by the contrast, so this is consistency, not an independent test."
          >
            samples sort into their arms {Math.round(purity * 100)}% cleanly for these genes
          </span>
        )}
      </div>
    </div>
  );
}

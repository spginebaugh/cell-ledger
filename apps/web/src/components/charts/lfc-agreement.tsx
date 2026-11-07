import { quadtree } from "d3-quadtree";
import { scaleLinear } from "d3-scale";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtLfc, fmtNum } from "@/lib/format";
import { cssVar } from "@/lib/theme";
import { decodePoints } from "@/lib/validation";
import type { ValidationComparison } from "@/lib/validation-results";
import { AxisBottom, AxisLeft, CHART, GridY, useMeasure } from "./common";

type Hit = { i: number; x: number; y: number };

/** The pipeline's log2 fold change against the authors' for one comparison. Points are the
 * hard-coded sample from the validation run; R² and Spearman are over every shared gene. */
export function LfcAgreement({
  comparison,
  themeKey,
}: {
  comparison: ValidationComparison;
  themeKey?: string;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<Hit | null>(null);
  const height = Math.max(240, Math.min(width, 380));
  const m = { top: 10, right: 14, bottom: 44, left: 52 };

  const pts = useMemo(() => decodePoints(comparison), [comparison]);
  const lim = comparison.lim;

  const x = useMemo(
    () =>
      scaleLinear()
        .domain([-lim, lim])
        .range([m.left, width - m.right]),
    [lim, width, m.left, m.right],
  );
  const y = useMemo(
    () =>
      scaleLinear()
        .domain([-lim, lim])
        .range([height - m.bottom, m.top]),
    [lim, height, m.bottom, m.top],
  );
  const clamp = useCallback((v: number) => Math.max(-lim, Math.min(lim, v)), [lim]);

  const tree = useMemo(() => {
    if (width === 0) return null;
    const hits: Hit[] = [];
    for (let i = 0; i < pts.n; i++) {
      hits.push({ i, x: x(clamp(pts.published[i])), y: y(clamp(pts.ours[i])) });
    }
    return quadtree<Hit>()
      .x((d) => d.x)
      .y((d) => d.y)
      .addAll(hits);
  }, [pts, x, y, width, clamp]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: themeKey forces a redraw when the CSS variables change
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = width * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);
    ctx.fillStyle = cssVar("--case");
    ctx.globalAlpha = 0.55;
    for (let i = 0; i < pts.n; i++) {
      ctx.beginPath();
      ctx.arc(x(clamp(pts.published[i])), y(clamp(pts.ours[i])), 2, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.globalAlpha = 1;
    // R² in the top-left corner, over the points
    const label = `R² = ${fmtNum(comparison.r2, 2)}`;
    ctx.font = "600 13px IBM Plex Sans, system-ui, sans-serif";
    ctx.textBaseline = "top";
    ctx.lineWidth = 4;
    ctx.strokeStyle = cssVar("--surface");
    ctx.strokeText(label, m.left + 8, m.top + 6);
    ctx.fillStyle = cssVar("--ink");
    ctx.fillText(label, m.left + 8, m.top + 6);
  }, [pts, x, y, width, height, clamp, comparison.r2, m.left, m.top, themeKey]);

  const onMove = (e: React.MouseEvent) => {
    if (!tree) return;
    const r = e.currentTarget.getBoundingClientRect();
    setHover(tree.find(e.clientX - r.left, e.clientY - r.top, 7) ?? null);
  };

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <>
          <svg width={width} height={height} className="absolute left-0 top-0" aria-hidden>
            <GridY scale={y} x0={m.left} x1={width - m.right} ticks={5} />
            <line
              x1={x(0)}
              x2={x(0)}
              y1={m.top}
              y2={height - m.bottom}
              stroke={CHART.grid}
              strokeDasharray="2 3"
            />
            <line
              x1={x(-lim)}
              x2={x(lim)}
              y1={y(-lim)}
              y2={y(lim)}
              stroke={CHART.ink3}
              strokeDasharray="4 3"
            />
            <AxisLeft scale={y} x={m.left} height={height} ticks={5} label="Cell Ledger log2FC" />
            <AxisBottom
              scale={x}
              y={height - m.bottom}
              width={width}
              ticks={5}
              label="published log2FC"
            />
          </svg>
          <canvas
            ref={canvasRef}
            style={{ width, height }}
            className="relative block cursor-crosshair"
            role="img"
            aria-label={`${comparison.title}: Cell Ledger against published log2 fold change for ${comparison.shared.toLocaleString()} genes, R² ${fmtNum(comparison.r2, 2)}, Spearman ${fmtNum(comparison.spearman, 2)}.`}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        </>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{pts.symbols[hover.i] || "unnamed gene"}</div>
          <div className="num text-ink-2">
            published {fmtLfc(pts.published[hover.i])} · Cell Ledger {fmtLfc(pts.ours[hover.i])}
          </div>
        </ChartTip>
      )}
      <div className="num mt-2 flex flex-wrap justify-between gap-x-3 text-[12px] text-ink-3">
        <span>
          R² {fmtNum(comparison.r2, 2)} · Spearman {fmtNum(comparison.spearman, 2)} ·{" "}
          {comparison.shared.toLocaleString()} shared genes
        </span>
        <span>{pts.n.toLocaleString()} drawn</span>
      </div>
    </div>
  );
}

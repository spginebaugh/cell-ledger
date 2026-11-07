import { max } from "d3-array";
import { quadtree } from "d3-quadtree";
import { scaleLinear } from "d3-scale";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtLfc, fmtP } from "@/lib/format";
import { cssVar } from "@/lib/theme";
import { countSignificant, type VolcanoTable } from "@/lib/volcano";
import { AxisBottom, AxisLeft, CHART, GridY, Legend, useMeasure } from "./common";

export type VolcanoProps = {
  table: VolcanoTable;
  alpha: number;
  lfc: number;
  /** symbols to ring and label (e.g. a selected term's leading genes) */
  highlight: Set<string>;
  /** one gene the user searched for; drawn larger with a label */
  focus: string | null;
  labelTop?: number;
  themeKey?: string;
};

type Hit = { i: number; x: number; y: number };

export function Volcano({
  table,
  alpha,
  lfc,
  highlight,
  focus,
  labelTop = 12,
  themeKey,
}: VolcanoProps) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<{ i: number; x: number; y: number } | null>(null);
  const height = 420;
  const m = { top: 10, right: 16, bottom: 44, left: 56 };

  const xMax = useMemo(() => {
    let v = 0;
    for (let i = 0; i < table.n; i++) {
      const a = Math.abs(table.log2fc[i]);
      if (!Number.isNaN(a) && a > v) v = a;
    }
    return Math.max(lfc * 1.2, v * 1.05, 1);
  }, [table, lfc]);
  // padj underflows to 0 for the strongest genes (-log10 pinned at 300); cap the axis at the
  // largest honest value so the bulk of the cloud keeps its shape, and pin capped points on top.
  const yMax = useMemo(() => {
    const honest = max(table.negLog, (v) => (Number.isNaN(v) || v >= 299 ? 0 : v)) ?? 0;
    return Math.max(2, honest * 1.06);
  }, [table]);
  const yCap = useCallback((v: number) => Math.min(v, yMax), [yMax]);

  const x = useMemo(
    () =>
      scaleLinear()
        .domain([-xMax, xMax])
        .range([m.left, width - m.right]),
    [xMax, width, m.left, m.right],
  );
  const y = useMemo(
    () =>
      scaleLinear()
        .domain([0, yMax])
        .range([height - m.bottom, m.top]),
    [yMax, m.bottom, m.top],
  );

  const symbolIndex = useMemo(() => {
    const map = new Map<string, number>();
    table.symbol.forEach((s, i) => {
      if (s) map.set(s.toUpperCase(), i);
    });
    return map;
  }, [table]);

  const tree = useMemo(() => {
    if (width === 0) return null;
    const hits: Hit[] = [];
    for (let i = 0; i < table.n; i++) {
      if (Number.isNaN(table.negLog[i]) || Number.isNaN(table.log2fc[i])) continue;
      hits.push({ i, x: x(table.log2fc[i]), y: y(yCap(table.negLog[i])) });
    }
    return quadtree<Hit>()
      .x((d) => d.x)
      .y((d) => d.y)
      .addAll(hits);
  }, [table, x, y, width, yCap]);

  const counts = useMemo(() => countSignificant(table, alpha, lfc), [table, alpha, lfc]);

  // Points of interest get labels: the top-N by padj among significant, plus highlights/focus.
  const labelled = useMemo(() => {
    const idx: number[] = [];
    for (let i = 0; i < table.n; i++) {
      const p = table.padj[i];
      if (!Number.isNaN(p) && p < alpha && Math.abs(table.log2fc[i]) >= lfc && table.symbol[i])
        idx.push(i);
    }
    // ties at padj = 0 are broken by effect size so labels spread along the cap line
    idx.sort(
      (a, b) =>
        table.padj[a] - table.padj[b] || Math.abs(table.log2fc[b]) - Math.abs(table.log2fc[a]),
    );
    const top = new Set(idx.slice(0, labelTop));
    for (const s of highlight) {
      const i = symbolIndex.get(s.toUpperCase());
      if (i !== undefined) top.add(i);
    }
    if (focus) {
      const i = symbolIndex.get(focus.toUpperCase());
      if (i !== undefined) top.add(i);
    }
    return top;
  }, [table, alpha, lfc, labelTop, highlight, focus, symbolIndex]);

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
    const cCase = cssVar("--case");
    const cControl = cssVar("--control");
    const cMuted = cssVar("--muted");
    const cInk = cssVar("--ink");
    const cSurface = cssVar("--surface");
    const hi = new Set<number>();
    for (const s of highlight) {
      const i = symbolIndex.get(s.toUpperCase());
      if (i !== undefined) hi.add(i);
    }
    const focusIdx = focus ? symbolIndex.get(focus.toUpperCase()) : undefined;
    const dimOthers = hi.size > 0 || focusIdx !== undefined;
    // pass 1: not significant
    ctx.globalAlpha = dimOthers ? 0.25 : 0.55;
    ctx.fillStyle = cMuted;
    for (let i = 0; i < table.n; i++) {
      const p = table.padj[i];
      if (Number.isNaN(p)) continue;
      const sig = p < alpha && Math.abs(table.log2fc[i]) >= lfc;
      if (sig) continue;
      ctx.fillRect(x(table.log2fc[i]) - 1, y(yCap(table.negLog[i])) - 1, 2, 2);
    }
    // pass 2: significant
    ctx.globalAlpha = dimOthers ? 0.3 : 0.85;
    for (let i = 0; i < table.n; i++) {
      const p = table.padj[i];
      if (Number.isNaN(p)) continue;
      const sig = p < alpha && Math.abs(table.log2fc[i]) >= lfc;
      if (!sig) continue;
      ctx.fillStyle = table.log2fc[i] > 0 ? cCase : cControl;
      ctx.beginPath();
      ctx.arc(x(table.log2fc[i]), y(yCap(table.negLog[i])), 2.2, 0, Math.PI * 2);
      ctx.fill();
    }
    // pass 3: highlighted + focus
    ctx.globalAlpha = 1;
    const ring = (i: number, r: number) => {
      if (Number.isNaN(table.negLog[i])) return;
      const px = x(table.log2fc[i]);
      const py = y(yCap(table.negLog[i]));
      ctx.fillStyle = table.log2fc[i] > 0 ? cCase : cControl;
      ctx.strokeStyle = cSurface;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(px, py, r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    };
    for (const i of hi) ring(i, 4);
    if (focusIdx !== undefined) {
      ring(focusIdx, 6);
      const px = x(table.log2fc[focusIdx]);
      const py = y(yCap(table.negLog[focusIdx]));
      if (!Number.isNaN(py)) {
        ctx.strokeStyle = cInk;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.arc(px, py, 9, 0, Math.PI * 2);
        ctx.stroke();
      }
    }
    // labels
    ctx.font = "11px IBM Plex Sans, system-ui, sans-serif";
    ctx.textBaseline = "bottom";
    const placed: { x: number; y: number }[] = [];
    for (const i of labelled) {
      if (Number.isNaN(table.negLog[i])) continue;
      const px = x(table.log2fc[i]) + 5;
      const py0 = y(yCap(table.negLog[i]));
      // points pinned on the cap line get their label below them so it is not clipped
      const py = py0 < m.top + 16 ? py0 + 14 : py0 - 3;
      if (placed.some((q) => Math.abs(q.x - px) < 40 && Math.abs(q.y - py) < 12)) continue;
      placed.push({ x: px, y: py });
      const s = table.symbol[i] ?? "";
      ctx.lineWidth = 3;
      ctx.strokeStyle = cSurface;
      ctx.strokeText(s, px, py);
      ctx.fillStyle = cInk;
      ctx.fillText(s, px, py);
    }
  }, [table, alpha, lfc, highlight, focus, labelled, symbolIndex, width, x, y, yCap, themeKey]);

  const onMove = (e: React.MouseEvent) => {
    if (!tree) return;
    const r = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - r.left;
    const py = e.clientY - r.top;
    const hit = tree.find(px, py, 8);
    setHover(hit ? { i: hit.i, x: hit.x, y: hit.y } : null);
  };

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <>
          <svg width={width} height={height} className="absolute left-0 top-0" aria-hidden>
            <GridY scale={y} x0={m.left} x1={width - m.right} />
            <line
              x1={x(-lfc)}
              x2={x(-lfc)}
              y1={m.top}
              y2={height - m.bottom}
              stroke={CHART.ink3}
              strokeDasharray="2 3"
            />
            <line
              x1={x(lfc)}
              x2={x(lfc)}
              y1={m.top}
              y2={height - m.bottom}
              stroke={CHART.ink3}
              strokeDasharray="2 3"
            />
            <line
              x1={m.left}
              x2={width - m.right}
              y1={y(-Math.log10(alpha))}
              y2={y(-Math.log10(alpha))}
              stroke={CHART.ink3}
              strokeDasharray="2 3"
            />
            <AxisLeft
              scale={y}
              x={m.left}
              height={height}
              label={
                yMax < 299
                  ? `−log10 adjusted p (top line: padj < 1e-${Math.round(yMax)})`
                  : "−log10 adjusted p"
              }
            />
            <AxisBottom
              scale={x}
              y={height - m.bottom}
              width={width}
              label="log2 fold change (case vs control)"
            />
          </svg>
          <canvas
            ref={canvasRef}
            style={{ width, height }}
            className="relative block cursor-crosshair"
            role="img"
            aria-label={`Volcano plot: ${counts.up} genes higher in case, ${counts.down} higher in control`}
            onMouseMove={onMove}
            onMouseLeave={() => setHover(null)}
          />
        </>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{table.symbol[hover.i] ?? table.geneId[hover.i]}</div>
          <div className="text-ink-2">
            log2FC {fmtLfc(table.log2fc[hover.i])} · padj {fmtP(table.padj[hover.i])}
          </div>
          <div className="accession text-ink-3">GeneID {table.geneId[hover.i]}</div>
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Legend
          items={[
            { label: `higher in case (${counts.up.toLocaleString()})`, color: CHART.case },
            { label: `higher in control (${counts.down.toLocaleString()})`, color: CHART.control },
            { label: "not significant", color: CHART.muted },
          ]}
        />
        <span className="num text-[12px] text-ink-3">
          {counts.tested.toLocaleString()} genes with an adjusted p
        </span>
      </div>
    </div>
  );
}

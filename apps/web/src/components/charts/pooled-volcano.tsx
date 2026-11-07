import { max } from "d3-array";
import { quadtree } from "d3-quadtree";
import { scaleLinear } from "d3-scale";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtInt, fmtLfc, fmtP } from "@/lib/format";
import { countPooled, type PooledTable } from "@/lib/pooled";
import { cssVar } from "@/lib/theme";
import { AxisBottom, AxisLeft, CHART, GridY, Legend, useMeasure } from "./common";

type Hit = { i: number; x: number; y: number };

/** Opacity for a called gene from the share of datasets that found it: a gene seen in every
 * study is solid, one carried by the pool alone is faint. */
function replicationAlpha(frac: number): number {
  return 0.22 + 0.78 * Math.max(0, Math.min(1, frac));
}

/** The volcano for the pooled estimate: one point per gene across every dataset. Position is
 * the pooled fold change and confidence, as on a single study, and colour depth is replication,
 * how many of the datasets found the same change on their own. Hover for the gene's forest. */
export function PooledVolcano({
  table,
  alpha,
  lfc,
  highlight,
  pin = [],
  selected = null,
  onSelect,
  labelTop = 14,
  themeKey,
}: {
  table: PooledTable;
  alpha: number;
  lfc: number;
  /** symbols to ring and label (a selected pathway's leading genes) */
  highlight: Set<string>;
  /** symbols always labelled (the genes the question asked about) */
  pin?: string[];
  selected?: string | null;
  onSelect?: (symbol: string, geneId: string) => void;
  labelTop?: number;
  themeKey?: string;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<Hit | null>(null);
  const height = 440;
  const m = { top: 10, right: 16, bottom: 44, left: 56 };
  const cut = -Math.log10(alpha);

  const xMax = useMemo(() => {
    let v = 0;
    for (let i = 0; i < table.n; i++) {
      const a = Math.abs(table.log2fc[i]);
      if (!Number.isNaN(a) && a > v) v = a;
    }
    return Math.max(lfc * 1.2, v * 1.05, 1);
  }, [table, lfc]);
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
  const called = useCallback(
    (i: number) => {
      const nl = table.negLog[i];
      return !Number.isNaN(nl) && nl >= cut && Math.abs(table.log2fc[i]) >= lfc;
    },
    [table, cut, lfc],
  );
  const tree = useMemo(() => {
    if (width === 0) return null;
    const hits: Hit[] = [];
    for (let i = 0; i < table.n; i++) {
      if (Number.isNaN(table.negLog[i])) continue;
      hits.push({ i, x: x(table.log2fc[i]), y: y(yCap(table.negLog[i])) });
    }
    return quadtree<Hit>()
      .x((d) => d.x)
      .y((d) => d.y)
      .addAll(hits);
  }, [table, x, y, width, yCap]);
  const counts = useMemo(() => countPooled(table, alpha, lfc), [table, alpha, lfc]);

  const labelled = useMemo(() => {
    const idx: number[] = [];
    for (let i = 0; i < table.n; i++) if (called(i) && table.symbol[i]) idx.push(i);
    // the most replicated first, then the surest, then the largest effect
    idx.sort(
      (a, b) =>
        table.nSig[b] / table.nTested[b] - table.nSig[a] / table.nTested[a] ||
        table.negLog[b] - table.negLog[a] ||
        Math.abs(table.log2fc[b]) - Math.abs(table.log2fc[a]),
    );
    const top = new Set(idx.slice(0, labelTop));
    for (const s of [...highlight, ...pin, selected ?? ""]) {
      const i = symbolIndex.get(s.toUpperCase());
      if (i !== undefined) top.add(i);
    }
    return top;
  }, [table, called, labelTop, highlight, pin, selected, symbolIndex]);

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
    const selectedIdx = selected ? symbolIndex.get(selected.toUpperCase()) : undefined;
    const dim = hi.size > 0 || selectedIdx !== undefined;
    // pass 1: not called
    ctx.globalAlpha = dim ? 0.2 : 0.5;
    ctx.fillStyle = cMuted;
    for (let i = 0; i < table.n; i++) {
      if (Number.isNaN(table.negLog[i]) || called(i)) continue;
      ctx.fillRect(x(table.log2fc[i]) - 1, y(yCap(table.negLog[i])) - 1, 2, 2);
    }
    // pass 2: called, depth and size by replication
    for (let i = 0; i < table.n; i++) {
      if (!called(i)) continue;
      const frac = table.nTested[i] ? table.nSig[i] / table.nTested[i] : 0;
      ctx.globalAlpha = (dim ? 0.35 : 1) * replicationAlpha(frac);
      ctx.fillStyle = table.log2fc[i] > 0 ? cCase : cControl;
      ctx.beginPath();
      ctx.arc(x(table.log2fc[i]), y(yCap(table.negLog[i])), 1.6 + 1.6 * frac, 0, Math.PI * 2);
      ctx.fill();
    }
    // pass 3: highlighted and selected
    ctx.globalAlpha = 1;
    const ring = (i: number, r: number) => {
      ctx.fillStyle = table.log2fc[i] > 0 ? cCase : cControl;
      ctx.strokeStyle = cSurface;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.arc(x(table.log2fc[i]), y(yCap(table.negLog[i])), r, 0, Math.PI * 2);
      ctx.fill();
      ctx.stroke();
    };
    for (const i of hi) ring(i, 4);
    if (selectedIdx !== undefined && !Number.isNaN(table.negLog[selectedIdx])) {
      ring(selectedIdx, 6);
      ctx.strokeStyle = cInk;
      ctx.lineWidth = 1.5;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.arc(x(table.log2fc[selectedIdx]), y(yCap(table.negLog[selectedIdx])), 9, 0, Math.PI * 2);
      ctx.stroke();
      ctx.setLineDash([]);
    }
    // labels
    ctx.font = "11px IBM Plex Sans, system-ui, sans-serif";
    ctx.textBaseline = "bottom";
    const placed: { x: number; y: number }[] = [];
    for (const i of labelled) {
      if (Number.isNaN(table.negLog[i])) continue;
      const px = x(table.log2fc[i]) + 5;
      const py0 = y(yCap(table.negLog[i]));
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
  }, [table, called, highlight, selected, labelled, symbolIndex, width, x, y, yCap, themeKey]);

  const hitAt = (e: React.MouseEvent) => {
    if (!tree) return null;
    const r = e.currentTarget.getBoundingClientRect();
    return tree.find(e.clientX - r.left, e.clientY - r.top, 8) ?? null;
  };
  const onClick = (e: React.MouseEvent) => {
    const hit = hitAt(e);
    if (!hit || !onSelect) return;
    const s = table.symbol[hit.i];
    if (s) onSelect(s, table.geneId[hit.i]);
  };
  const nMembers = table.members.filter((mm) => mm.pooled).length;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <>
          <svg width={width} height={height} className="absolute left-0 top-0" aria-hidden>
            <GridY scale={y} x0={m.left} x1={width - m.right} />
            {[-lfc, lfc].map((v) => (
              <line
                key={v}
                x1={x(v)}
                x2={x(v)}
                y1={m.top}
                y2={height - m.bottom}
                stroke={CHART.ink3}
                strokeDasharray="2 3"
              />
            ))}
            <line
              x1={m.left}
              x2={width - m.right}
              y1={y(cut)}
              y2={y(cut)}
              stroke={CHART.ink3}
              strokeDasharray="2 3"
            />
            <AxisLeft
              scale={y}
              x={m.left}
              height={height}
              label={
                yMax < 299
                  ? `−log10 pooled adjusted p (top line: padj < 1e-${Math.round(yMax)})`
                  : "−log10 pooled adjusted p"
              }
            />
            <AxisBottom
              scale={x}
              y={height - m.bottom}
              width={width}
              label={`pooled log2 fold change across ${nMembers} datasets (case vs control)`}
            />
          </svg>
          <canvas
            ref={canvasRef}
            style={{ width, height }}
            className={
              hover && onSelect
                ? "relative block cursor-pointer"
                : "relative block cursor-crosshair"
            }
            role="img"
            aria-label={`Pooled volcano plot: ${fmtInt(counts.up)} genes higher in case, ${fmtInt(counts.down)} higher in control across ${nMembers} datasets${onSelect ? ". Click a point to open its gene." : ""}`}
            onMouseMove={(e) => setHover(hitAt(e))}
            onMouseLeave={() => setHover(null)}
            onClick={onClick}
          />
        </>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{table.symbol[hover.i] ?? table.geneId[hover.i]}</div>
          <div className="num text-ink-2">
            pooled log2FC {fmtLfc(table.log2fc[hover.i])} · padj{" "}
            {fmtP(10 ** -table.negLog[hover.i])}
          </div>
          <div className="num text-ink-2">
            significant in {table.nSig[hover.i]} of {table.nTested[hover.i]} datasets · same
            direction in {table.nAgree[hover.i]}
          </div>
          <MiniForest table={table} i={hover.i} />
          {onSelect && table.symbol[hover.i] && (
            <div className="mt-0.5 text-ink-3">Click to open the gene</div>
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
        <Legend
          items={[
            { label: `higher in case (${fmtInt(counts.up)})`, color: CHART.case },
            { label: `higher in control (${fmtInt(counts.down)})`, color: CHART.control },
            { label: "not called", color: CHART.muted },
          ]}
        />
        <span className="inline-flex items-center gap-2 text-[12px] text-ink-3">
          <span className="inline-flex items-center gap-0.5" aria-hidden>
            {[0.15, 0.5, 1].map((f) => (
              <span
                key={f}
                className="inline-block rounded-full bg-ink"
                style={{
                  width: 4 + 6 * f,
                  height: 4 + 6 * f,
                  opacity: replicationAlpha(f),
                }}
              />
            ))}
          </span>
          darker and bigger: found in more datasets · {fmtInt(counts.pooled)} genes pooled
        </span>
      </div>
    </div>
  );
}

/** The hovered gene in every pooled dataset: a point and 95% interval per dataset, the pooled
 * estimate as a diamond. Small enough to live in a tooltip. */
function MiniForest({ table, i }: { table: PooledTable; i: number }) {
  const members = table.members.map((mm, j) => ({ mm, j })).filter(({ mm }) => mm.pooled);
  const W = 220;
  const rowH = 9;
  const H = rowH * (members.length + 1) + 6;
  let lo = Math.min(0, table.log2fc[i]);
  let hi = Math.max(0, table.log2fc[i]);
  for (const { j } of members) {
    const v = table.memberLfc[j][i];
    if (Number.isNaN(v)) continue;
    const se = table.memberSe[j][i] || 0;
    lo = Math.min(lo, v - 1.96 * se);
    hi = Math.max(hi, v + 1.96 * se);
  }
  const x = scaleLinear()
    .domain([lo, hi])
    .range([6, W - 6])
    .nice();
  return (
    <svg width={W} height={H} className="mt-1 block" aria-hidden>
      <line x1={x(0)} x2={x(0)} y1={2} y2={H - 2} stroke={CHART.ink3} strokeDasharray="2 2" />
      {members.map(({ j }, k) => {
        const v = table.memberLfc[j][i];
        const cy = 4 + k * rowH + rowH / 2;
        if (Number.isNaN(v))
          return (
            <text
              key={j}
              x={x(0)}
              y={cy}
              dy="0.32em"
              textAnchor="middle"
              fontSize={8}
              fill={CHART.ink3}
            >
              ×
            </text>
          );
        const se = table.memberSe[j][i] || 0;
        const c = v > 0 ? CHART.case : CHART.control;
        return (
          <g key={j} opacity={table.memberSig[j][i] ? 1 : 0.45}>
            <line x1={x(v - 1.96 * se)} x2={x(v + 1.96 * se)} y1={cy} y2={cy} stroke={c} />
            <circle cx={x(v)} cy={cy} r={2.4} fill={c} />
          </g>
        );
      })}
      {(() => {
        const p = table.log2fc[i];
        const cy = 4 + members.length * rowH + rowH / 2;
        return (
          <polygon
            points={`${x(p) - 5},${cy} ${x(p)},${cy - 4} ${x(p) + 5},${cy} ${x(p)},${cy + 4}`}
            fill={CHART.ink}
          />
        );
      })()}
    </svg>
  );
}

import {
  forceCenter,
  forceCollide,
  forceLink,
  forceManyBody,
  forceSimulation,
  forceX,
  forceY,
  type SimulationLinkDatum,
  type SimulationNodeDatum,
} from "d3-force";
import { scaleSqrt } from "d3-scale";
import { Maximize2, Minus, Plus } from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { Button } from "@/components/ui/button";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtNum } from "@/lib/format";
import { cn } from "@/lib/utils";
import { CHART, Legend, useMeasure } from "./common";
import { termLabel } from "./enrichment-bars";

type PathwayNode = SimulationNodeDatum & {
  id: string;
  kind: "pathway";
  term: EnrichmentTerm;
  r: number;
  /** keep-out radius for the label, so neighbours do not sit on it */
  pad: number;
};
type GeneNode = SimulationNodeDatum & {
  id: string;
  kind: "gene";
  symbol: string;
  degree: number;
  r: number;
  pad: number;
};
type Node = PathwayNode | GeneNode;
type Edge = SimulationLinkDatum<Node> & { source: Node; target: Node };

/** The view: scale k about the origin, then shift by (x, y), in SVG pixels. */
type View = { k: number; x: number; y: number };
const VIEW0: View = { k: 1, x: 0, y: 0 };
const K_MIN = 0.5;
const K_MAX = 6;
const DRAG_PX = 4; // pointer travel beyond which a press is a pan, not a click

/** Zoom by factor f keeping the SVG point (px, py) fixed under the cursor. */
function zoomAt(v: View, f: number, px: number, py: number): View {
  const k = Math.max(K_MIN, Math.min(K_MAX, v.k * f));
  const r = k / v.k;
  return { k, x: px - (px - v.x) * r, y: py - (py - v.y) * r };
}

const fmtFdr = (f: number) => (f < 1e-3 ? "<0.001" : f.toFixed(3));

function layout(
  terms: EnrichmentTerm[],
  width: number,
  height: number,
  genesPerTerm: number,
): { nodes: Node[]; edges: Edge[] } {
  const degree = new Map<string, number>();
  const pick = terms.map((t) => t.lead_genes.slice(0, genesPerTerm));
  for (const genes of pick) for (const g of genes) degree.set(g, (degree.get(g) ?? 0) + 1);
  const rScale = scaleSqrt()
    .domain([1, Math.max(1, ...terms.map((t) => Math.abs(t.nes)))])
    .range([11, 24]);
  const pNodes: PathwayNode[] = terms.map((t) => ({
    id: `p:${t.term}`,
    kind: "pathway",
    term: t,
    r: rScale(Math.max(1, Math.abs(t.nes))),
    pad: Math.max(0, termLabel(t.term).length * 3.4 - 12),
  }));
  const gNodes: GeneNode[] = [...degree.entries()].map(([symbol, d]) => ({
    id: `g:${symbol}`,
    kind: "gene",
    symbol,
    degree: d,
    r: d > 1 ? 5 : 3.5,
    pad: d > 1 ? symbol.length * 3 : 0,
  }));
  const byId = new Map<string, Node>([...pNodes, ...gNodes].map((n) => [n.id, n]));
  const edges: Edge[] = [];
  terms.forEach((t, i) => {
    for (const g of pick[i]) {
      const s = byId.get(`p:${t.term}`);
      const d = byId.get(`g:${g}`);
      if (s && d) edges.push({ source: s, target: d });
    }
  });
  const nodes: Node[] = [...pNodes, ...gNodes];
  const sim = forceSimulation<Node>(nodes)
    .force(
      "link",
      forceLink<Node, Edge>(edges)
        .id((d) => d.id)
        .distance((e) => (e.target.kind === "gene" && e.target.degree > 1 ? 70 : 38))
        .strength(0.5),
    )
    .force(
      "charge",
      forceManyBody<Node>().strength((d) => (d.kind === "pathway" ? -900 : -30)),
    )
    .force(
      "collide",
      forceCollide<Node>()
        .radius((d) => Math.max(d.r, d.pad) + (d.kind === "pathway" ? 18 : 4))
        .strength(0.9)
        .iterations(2),
    )
    .force("center", forceCenter(width / 2, height / 2))
    .force("x", forceX(width / 2).strength(0.03))
    .force("y", forceY(height / 2).strength(0.05))
    .stop();
  for (let i = 0; i < 400; i++) sim.tick();
  // keep every node, and its label, inside the frame
  for (const n of nodes) {
    const half = Math.max(n.r, n.pad) + 6;
    const above = n.kind === "gene" && n.degree > 1 ? 16 : n.r + 4;
    const below = n.kind === "pathway" ? n.r + 20 : n.r + 4;
    n.x = Math.max(half, Math.min(width - half, n.x ?? width / 2));
    n.y = Math.max(above, Math.min(height - below, n.y ?? height / 2));
  }
  return { nodes, edges };
}

/** Pathways as hubs joined to the genes that drive them. Pathways that share genes pull
 * together, so related programmes form visible clusters. Click a pathway to mark its genes on
 * the volcano; click a gene to open it. */
export function PathwayNetwork({
  terms,
  n = 12,
  genesPerTerm = 10,
  selected,
  onSelectTerm,
  onSelectGene,
  canPick,
  height = 560,
}: {
  terms: EnrichmentTerm[];
  n?: number;
  genesPerTerm?: number;
  selected: string | null;
  onSelectTerm?: (term: EnrichmentTerm | null) => void;
  onSelectGene?: (symbol: string) => void;
  canPick?: (symbol: string) => boolean;
  height?: number;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const svgRef = useRef<SVGSVGElement>(null);
  const [hover, setHover] = useState<{ node: Node; x: number; y: number } | null>(null);
  const [view, setView] = useState<View>(VIEW0);
  // A press that travels becomes a pan; the click that follows it is swallowed.
  const drag = useRef<{ id: number; x0: number; y0: number; vx: number; vy: number } | null>(null);
  const [panning, setPanning] = useState(false);
  const moved = useRef(false);
  const shown = useMemo(
    () => [...terms].sort((a, b) => a.fdr - b.fdr || Math.abs(b.nes) - Math.abs(a.nes)).slice(0, n),
    [terms, n],
  );
  const { nodes, edges } = useMemo(
    () => (width > 0 ? layout(shown, width, height, genesPerTerm) : { nodes: [], edges: [] }),
    [shown, width, height, genesPerTerm],
  );
  const selGenes = useMemo(() => {
    const t = shown.find((t) => t.term === selected);
    return new Set(t?.lead_genes.slice(0, genesPerTerm) ?? []);
  }, [shown, selected, genesPerTerm]);
  const dim = selected !== null && shown.some((t) => t.term === selected);
  const nShared = nodes.filter((d) => d.kind === "gene" && d.degree > 1).length;

  const place = (e: React.MouseEvent, node: Node) => {
    if (drag.current && moved.current) return;
    const rect = (e.currentTarget as SVGElement).ownerSVGElement?.getBoundingClientRect();
    if (!rect) return;
    setHover({ node, x: e.clientX - rect.left, y: e.clientY - rect.top });
  };

  // Wheel zoom needs a non-passive listener to keep the page from scrolling under the map;
  // React registers wheel handlers passively, so attach it by hand.
  useEffect(() => {
    const svg = svgRef.current;
    if (!svg) return;
    const onWheel = (e: WheelEvent) => {
      e.preventDefault();
      const rect = svg.getBoundingClientRect();
      const f = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : 0.0025));
      setView((v) => zoomAt(v, f, e.clientX - rect.left, e.clientY - rect.top));
      setHover(null);
    };
    svg.addEventListener("wheel", onWheel, { passive: false });
    return () => svg.removeEventListener("wheel", onWheel);
  }, []);

  const onPointerDown = (e: React.PointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return;
    drag.current = { id: e.pointerId, x0: e.clientX, y0: e.clientY, vx: view.x, vy: view.y };
    moved.current = false;
  };
  const onPointerMove = (e: React.PointerEvent<SVGSVGElement>) => {
    const d = drag.current;
    if (!d || d.id !== e.pointerId) return;
    const dx = e.clientX - d.x0;
    const dy = e.clientY - d.y0;
    if (!moved.current && Math.hypot(dx, dy) < DRAG_PX) return;
    if (!moved.current) {
      moved.current = true;
      setPanning(true);
      setHover(null);
      e.currentTarget.setPointerCapture(e.pointerId);
    }
    setView((v) => ({ ...v, x: d.vx + dx, y: d.vy + dy }));
  };
  const endDrag = (e: React.PointerEvent<SVGSVGElement>) => {
    if (drag.current?.id !== e.pointerId) return;
    drag.current = null;
    setPanning(false);
    if (e.currentTarget.hasPointerCapture(e.pointerId))
      e.currentTarget.releasePointerCapture(e.pointerId);
  };
  // Swallow the click a pan would otherwise fire on whatever node it ended over.
  const onClickCapture = (e: React.MouseEvent) => {
    if (moved.current) {
      e.stopPropagation();
      moved.current = false;
    }
  };
  const zoomButton = (f: number) => setView((v) => zoomAt(v, f, width / 2, height / 2));
  const zoomed = view.k !== 1 || view.x !== 0 || view.y !== 0;

  if (shown.length === 0) return null;

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          ref={svgRef}
          width={width}
          height={height}
          role="img"
          aria-label={`${shown.length} pathways joined to their ${nodes.length - shown.length} leading genes. Scroll to zoom, drag to pan.`}
          className={cn(
            "rounded-md border border-line bg-surface touch-none select-none",
            panning ? "cursor-grabbing" : "cursor-grab",
          )}
          onPointerDown={onPointerDown}
          onPointerMove={onPointerMove}
          onPointerUp={endDrag}
          onPointerCancel={endDrag}
          onClickCapture={onClickCapture}
          onDoubleClick={() => setView(VIEW0)}
        >
          <g transform={`translate(${view.x},${view.y}) scale(${view.k})`}>
            {edges.map((e) => {
              const on = !dim || e.source.id === `p:${selected}`;
              return (
                <line
                  key={`${e.source.id}-${e.target.id}`}
                  x1={e.source.x}
                  y1={e.source.y}
                  x2={e.target.x}
                  y2={e.target.y}
                  stroke={on && dim ? CHART.ink2 : CHART.grid}
                  strokeWidth={on && dim ? 1.4 : 1}
                  opacity={on ? 1 : 0.25}
                />
              );
            })}
            {nodes.map((d) => {
              if (d.kind === "gene") {
                const on = !dim || selGenes.has(d.symbol);
                const pickable = Boolean(onSelectGene && (canPick ? canPick(d.symbol) : true));
                return (
                  <g
                    key={d.id}
                    role="graphics-symbol"
                    aria-label={`${d.symbol}, in ${d.degree} of these sets`}
                    transform={`translate(${d.x},${d.y})`}
                    opacity={on ? 1 : 0.2}
                    className={cn(pickable && "cursor-pointer")}
                    onMouseMove={(e) => place(e, d)}
                    onMouseLeave={() => setHover(null)}
                    onClick={() => pickable && onSelectGene?.(d.symbol)}
                  >
                    <circle r={d.r + 6} fill="transparent" />
                    <circle
                      r={d.r}
                      fill={d.degree > 1 ? CHART.ink2 : CHART.muted}
                      stroke={CHART.surface}
                      strokeWidth={1.2}
                    />
                    {(d.degree > 1 || (dim && on)) && (
                      <text
                        y={-d.r - 3}
                        textAnchor="middle"
                        fontSize={10}
                        fontFamily="var(--font-mono)"
                        fill={CHART.ink}
                        stroke="var(--surface)"
                        strokeWidth={3}
                        paintOrder="stroke"
                      >
                        {d.symbol}
                      </text>
                    )}
                  </g>
                );
              }
              const isSel = selected === d.term.term;
              const on = !dim || isSel;
              const color = d.term.nes > 0 ? CHART.case : CHART.control;
              return (
                <g
                  key={d.id}
                  role="graphics-symbol"
                  aria-label={`${termLabel(d.term.term)}: NES ${fmtNum(d.term.nes)}`}
                  transform={`translate(${d.x},${d.y})`}
                  opacity={on ? 1 : 0.35}
                  className={cn(onSelectTerm && "cursor-pointer")}
                  onMouseMove={(e) => place(e, d)}
                  onMouseLeave={() => setHover(null)}
                  onClick={() => onSelectTerm?.(isSel ? null : d.term)}
                >
                  {isSel && (
                    <circle r={d.r + 5} fill="none" stroke="var(--accent)" strokeWidth={2} />
                  )}
                  <circle
                    r={d.r}
                    fill={color}
                    fillOpacity={0.9}
                    stroke={CHART.surface}
                    strokeWidth={1.5}
                  />
                  <text
                    y={d.r + 12}
                    textAnchor="middle"
                    fontSize={11}
                    fontWeight={600}
                    fill={CHART.ink}
                    stroke="var(--surface)"
                    strokeWidth={3}
                    paintOrder="stroke"
                  >
                    {termLabel(d.term.term)}
                  </text>
                </g>
              );
            })}
          </g>
        </svg>
      )}
      {width > 0 && (
        <div className="absolute right-2 top-2 flex items-center gap-1">
          <Button
            size="sm"
            className="h-7 w-7 p-0"
            aria-label="Zoom in"
            onClick={() => zoomButton(1.4)}
          >
            <Plus size={14} />
          </Button>
          <Button
            size="sm"
            className="h-7 w-7 p-0"
            aria-label="Zoom out"
            onClick={() => zoomButton(1 / 1.4)}
          >
            <Minus size={14} />
          </Button>
          <Button
            size="sm"
            className="h-7 w-7 p-0"
            aria-label="Reset view"
            disabled={!zoomed}
            onClick={() => setView(VIEW0)}
          >
            <Maximize2 size={14} />
          </Button>
        </div>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          {hover.node.kind === "pathway" ? (
            <>
              <div className="font-medium">{termLabel(hover.node.term.term)}</div>
              <div className="num text-ink-2">
                NES {hover.node.term.nes > 0 ? "+" : "−"}
                {Math.abs(hover.node.term.nes).toFixed(2)} · FDR {fmtFdr(hover.node.term.fdr)} ·{" "}
                {hover.node.term.size} genes
              </div>
              {onSelectTerm && (
                <div className="mt-0.5 text-ink-3">Click to mark its genes on the volcano</div>
              )}
            </>
          ) : (
            <>
              <div className="font-mono font-medium">{hover.node.symbol}</div>
              <div className="text-ink-2">
                leads {hover.node.degree} of these {shown.length} sets
              </div>
              {onSelectGene && (canPick ? canPick(hover.node.symbol) : true) && (
                <div className="mt-0.5 text-ink-3">Click to open the gene</div>
              )}
            </>
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-2">
        <Legend
          items={[
            { label: "set enriched in case", color: CHART.case },
            { label: "set enriched in control", color: CHART.control },
            { label: "gene shared by several sets", color: CHART.ink2 },
            { label: "gene in one set", color: CHART.muted },
          ]}
        />
        <span className="num text-ink-3">
          top {shown.length} sets by FDR · up to {genesPerTerm} leading genes each · {nShared}{" "}
          shared · scroll to zoom, drag to pan, double-click to reset
        </span>
      </div>
    </div>
  );
}

import { useEffect, useMemo, useRef, useState } from "react";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtInt, fmtLfc } from "@/lib/format";
import { memberAgreement, type PooledTable, wallOrder } from "@/lib/pooled";
import { cssVar } from "@/lib/theme";
import { CHART, Legend, useMeasure } from "./common";

const HEAD_H = 66;
const FOOT_H = 42; // the agreement share under each column, then 'set aside'
const BAND_W = 118; // the left gutter: a bar and a count for each direction block
const GAP = 16; // between the pool and the datasets set aside
const MIN_COL = 18;
const RIGHT_PAD = 48; // the last rotated header overhangs its column
const MAX_COL = 60;
const FAINT = 0.4; // weight of a dataset's estimate that was not significant there

function hexToRgb(hex: string): [number, number, number] {
  const h = hex.replace("#", "");
  const v =
    h.length === 3
      ? h
          .split("")
          .map((c) => c + c)
          .join("")
      : h;
  const n = Number.parseInt(v.slice(0, 6), 16);
  return [(n >> 16) & 255, (n >> 8) & 255, n & 255];
}

type Cell = { j: number; from: number; to: number; x: number; y: number };

/** Every robust gene (rows) in every dataset (columns), the whole genome at once. A row is one
 * gene; its colour in a column is which way that dataset alone saw it move, solid when that
 * dataset called it significant and faint when it did not. Genes are two blocks, higher in case
 * then higher in control, so agreement reads as two unbroken bands running across every column.
 * When there are more genes than pixels, each pixel row averages the genes in it. */
export function AgreementWall({
  table,
  height = 480,
  onSelect,
  themeKey,
}: {
  table: PooledTable;
  height?: number;
  onSelect?: (symbol: string, geneId: string) => void;
  themeKey?: string;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hover, setHover] = useState<(Cell & { px: number; py: number }) | null>(null);

  const order = useMemo(() => wallOrder(table), [table]);
  const agreement = useMemo(() => memberAgreement(table), [table]);
  const nUp = useMemo(() => order.filter((i) => table.log2fc[i] > 0).length, [order, table]);
  const pooled = table.members.filter((m) => m.pooled);
  const aside = table.members.filter((m) => !m.pooled);
  const cols = table.members.length;
  const avail = width - BAND_W - (aside.length ? GAP : 0) - RIGHT_PAD;
  const col = Math.max(MIN_COL, Math.min(MAX_COL, avail / Math.max(1, cols)));
  const svgW = Math.max(width, BAND_W + cols * col + (aside.length ? GAP : 0) + RIGHT_PAD);
  const plotH = height - HEAD_H - FOOT_H;
  const rows = order.length;
  const rowPx = rows > 0 ? plotH / rows : 0;
  // column j's left edge: pooled members first, a gap, then the set-aside ones
  const colX = (j: number) => BAND_W + j * col + (j >= pooled.length ? GAP : 0);
  const colAt = (x: number) => {
    for (let j = 0; j < cols; j++) if (x >= colX(j) && x < colX(j) + col) return j;
    return -1;
  };

  // biome-ignore lint/correctness/useExhaustiveDependencies: themeKey forces a redraw when the CSS variables change
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas || width === 0 || rows === 0) return;
    const dpr = window.devicePixelRatio || 1;
    canvas.width = svgW * dpr;
    canvas.height = height * dpr;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, svgW, height);
    const cCase = hexToRgb(cssVar("--case") || "#2b6fc8");
    const cControl = hexToRgb(cssVar("--control") || "#d3602a");
    const cEmpty = cssVar("--surface-2") || "#eceff0";
    // one pass per pixel row: average every gene that lands in it
    const pxRows = Math.max(1, Math.min(rows, Math.floor(plotH)));
    const step = rows / pxRows;
    const rowH = plotH / pxRows;
    for (let k = 0; k < pxRows; k++) {
      const from = Math.floor(k * step);
      const to = Math.max(from + 1, Math.floor((k + 1) * step));
      const y = HEAD_H + k * rowH;
      for (let j = 0; j < cols; j++) {
        const lfc = table.memberLfc[j];
        const sig = table.memberSig[j];
        let sum = 0;
        let tested = 0;
        for (let r = from; r < to; r++) {
          const i = order[r];
          const v = lfc[i];
          if (Number.isNaN(v) || v === 0) continue;
          tested++;
          sum += (v > 0 ? 1 : -1) * (sig[i] ? 1 : FAINT);
        }
        const x = colX(j);
        if (tested === 0) {
          ctx.fillStyle = cEmpty;
          ctx.fillRect(x, y, col - 1, rowH + 0.5);
          continue;
        }
        const mean = sum / tested;
        const [r, g, b] = mean >= 0 ? cCase : cControl;
        const a = 0.18 + Math.abs(mean) * 0.82;
        ctx.fillStyle = `rgba(${r},${g},${b},${a.toFixed(3)})`;
        ctx.fillRect(x, y, col - 1, rowH + 0.5);
      }
    }
  }, [table, order, width, svgW, height, rows, cols, col, plotH, pooled.length, themeKey]);

  const cellAt = (e: React.MouseEvent): (Cell & { px: number; py: number }) | null => {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = e.clientX - rect.left;
    const py = e.clientY - rect.top;
    const j = colAt(px);
    if (j < 0 || py < HEAD_H || py >= HEAD_H + plotH || rows === 0) return null;
    const frac = (py - HEAD_H) / plotH;
    const pxRows = Math.max(1, Math.min(rows, Math.floor(plotH)));
    const k = Math.min(pxRows - 1, Math.floor(frac * pxRows));
    const step = rows / pxRows;
    const from = Math.floor(k * step);
    const to = Math.max(from + 1, Math.floor((k + 1) * step));
    return { j, from, to, x: colX(j), y: HEAD_H + k * (plotH / pxRows), px, py };
  };

  if (rows === 0)
    return <p className="text-sm text-ink-3">No robust genes to draw across datasets.</p>;

  const upH = rowPx * nUp;
  const downH = plotH - upH;
  const single = hover && hover.to - hover.from === 1 ? order[hover.from] : null;

  return (
    <div ref={ref} className="relative w-full overflow-x-auto">
      {width > 0 && (
        <div className="relative" style={{ width: svgW, height }}>
          <canvas
            ref={canvasRef}
            style={{ width: svgW, height }}
            className={single !== null && onSelect ? "block cursor-pointer" : "block"}
            role="img"
            aria-label={`${fmtInt(rows)} robust genes across ${cols} datasets: ${fmtInt(nUp)} higher in case, ${fmtInt(rows - nUp)} higher in control`}
            onMouseMove={(e) => setHover(cellAt(e))}
            onMouseLeave={() => setHover(null)}
            onClick={(e) => {
              const c = cellAt(e);
              if (!c || !onSelect || c.to - c.from !== 1) return;
              const i = order[c.from];
              const s = table.symbol[i];
              if (s) onSelect(s, table.geneId[i]);
            }}
          />
          <svg
            width={svgW}
            height={height}
            className="pointer-events-none absolute left-0 top-0"
            aria-hidden
          >
            {table.members.map((m, j) => (
              <text
                key={m.label}
                transform={`translate(${colX(j) + col / 2},${HEAD_H - 10}) rotate(-45)`}
                fontSize={11}
                fill={m.pooled ? CHART.ink2 : "var(--danger)"}
                fontFamily="var(--font-mono)"
              >
                {m.gse}
              </text>
            ))}
            {aside.length > 0 && (
              <text
                x={colX(pooled.length) + (aside.length * col) / 2}
                y={HEAD_H + plotH + 32}
                textAnchor="middle"
                fontSize={10}
                fill="var(--danger)"
                fontWeight={600}
              >
                set aside
              </text>
            )}
            {table.members.map((m, j) => {
              const a = agreement[j];
              return (
                <text
                  key={m.label}
                  x={colX(j) + col / 2}
                  y={HEAD_H + plotH + 15}
                  textAnchor="middle"
                  fontSize={11}
                  fill={a !== null && a < 0.5 ? "var(--danger)" : CHART.ink2}
                  className="num"
                >
                  {a === null ? "" : `${Math.round(a * 100)}%`}
                </text>
              );
            })}
            {/* the two blocks: a bar and a count, in the arm colours */}
            {upH > 0 && (
              <g>
                <rect x={BAND_W - 14} y={HEAD_H} width={4} height={upH} fill={CHART.case} rx={1} />
                <text
                  x={BAND_W - 24}
                  y={HEAD_H + Math.min(upH / 2, Math.max(14, upH / 2))}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={12}
                  fill={CHART.case}
                  fontWeight={600}
                  className="num"
                >
                  {fmtInt(nUp)} higher
                </text>
                <text
                  x={BAND_W - 24}
                  y={HEAD_H + Math.min(upH / 2, Math.max(14, upH / 2)) + 15}
                  textAnchor="end"
                  fontSize={11}
                  fill={CHART.ink2}
                >
                  in case
                </text>
              </g>
            )}
            {downH > 0 && (
              <g>
                <rect
                  x={BAND_W - 14}
                  y={HEAD_H + upH}
                  width={4}
                  height={downH}
                  fill={CHART.control}
                  rx={1}
                />
                <text
                  x={BAND_W - 24}
                  y={HEAD_H + upH + downH / 2}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={12}
                  fill={CHART.control}
                  fontWeight={600}
                  className="num"
                >
                  {fmtInt(rows - nUp)} higher
                </text>
                <text
                  x={BAND_W - 24}
                  y={HEAD_H + upH + downH / 2 + 15}
                  textAnchor="end"
                  fontSize={11}
                  fill={CHART.ink2}
                >
                  in control
                </text>
              </g>
            )}
            {hover && (
              <rect
                x={hover.x - 1}
                y={HEAD_H}
                width={col + 1}
                height={plotH}
                fill="none"
                stroke={CHART.ink}
                strokeOpacity={0.35}
              />
            )}
          </svg>
        </div>
      )}
      {hover && (
        <ChartTip x={hover.px} y={hover.py} width={width}>
          <div className="accession font-medium">
            {table.members[hover.j].label.replace(/:/, " · ").replaceAll("_", " ")}
          </div>
          {single !== null ? (
            <>
              <div className="font-medium">{table.symbol[single] ?? table.geneId[single]}</div>
              <div className="num text-ink-2">
                here {fmtLfc(table.memberLfc[hover.j][single])}
                {Number.isNaN(table.memberLfc[hover.j][single])
                  ? " (not tested)"
                  : table.memberSig[hover.j][single]
                    ? ", significant"
                    : ", not significant"}{" "}
                · pooled {fmtLfc(table.log2fc[single])}
              </div>
              {onSelect && table.symbol[single] && (
                <div className="mt-0.5 text-ink-3">Click to open the gene</div>
              )}
            </>
          ) : (
            <div className="num text-ink-2">
              genes {fmtInt(hover.from + 1)} to {fmtInt(hover.to)} of {fmtInt(rows)}
            </div>
          )}
          {agreement[hover.j] !== null && (
            <div className="num text-ink-3">
              {Math.round((agreement[hover.j] as number) * 100)}% of robust genes point the pooled
              way in this dataset
            </div>
          )}
        </ChartTip>
      )}
      <div className="mt-2 flex flex-wrap items-center justify-between gap-2 text-[12px] text-ink-2">
        <Legend
          items={[
            { label: "higher in case in that dataset", color: CHART.case },
            { label: "higher in control in that dataset", color: CHART.control },
            { label: "not tested there", color: "var(--surface-2)" },
          ]}
        />
        <span>solid: that dataset called it significant · faint: it did not</span>
      </div>
    </div>
  );
}

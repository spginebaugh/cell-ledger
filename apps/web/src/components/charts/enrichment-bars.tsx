import { max } from "d3-array";
import { scaleLinear } from "d3-scale";
import { useState } from "react";
import type { EnrichmentTerm } from "@/api/generated/types.gen";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtNum } from "@/lib/format";
import { AxisBottom, CHART, Legend, useMeasure } from "./common";

export function EnrichmentBars({
  terms,
  selected,
  onSelect,
  n = 15,
}: {
  terms: EnrichmentTerm[];
  selected: string | null;
  onSelect: (term: EnrichmentTerm | null) => void;
  n?: number;
}) {
  const [ref, width] = useMeasure<HTMLDivElement>();
  const [hover, setHover] = useState<{ t: EnrichmentTerm; x: number; y: number } | null>(null);
  const shown = [...terms].slice(0, n).sort((a, b) => a.nes - b.nes);
  const rowH = 22;
  const m = { top: 6, right: 72, bottom: 44, left: 230 };
  const labelW = Math.min(m.left, Math.max(120, width * 0.38));
  const height = m.top + m.bottom + shown.length * rowH;
  const amax = (max(shown, (t) => Math.abs(t.nes)) ?? 1) * 1.1;
  const x = scaleLinear()
    .domain([-amax, amax])
    .range([labelW, width - m.right])
    .nice();

  return (
    <div ref={ref} className="relative w-full">
      {width > 0 && (
        <svg
          width={width}
          height={height}
          role="img"
          aria-label="GSEA normalized enrichment scores"
        >
          <line x1={x(0)} x2={x(0)} y1={m.top} y2={height - m.bottom} stroke={CHART.ink2} />
          {shown.map((t, i) => {
            const y = m.top + i * rowH;
            const isSel = selected === t.term;
            const dim = selected !== null && !isSel;
            const label = t.term
              .replace(/^HALLMARK_/, "")
              .replaceAll("_", " ")
              .toLowerCase();
            return (
              <g
                key={t.term}
                className="cursor-pointer"
                onClick={() => onSelect(isSel ? null : t)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" || e.key === " ") onSelect(isSel ? null : t);
                }}
                role="graphics-symbol"
                tabIndex={0}
                aria-label={`${label}, NES ${fmtNum(t.nes)}, FDR ${fmtNum(t.fdr)}${isSel ? ", selected" : ""}`}
                onMouseMove={(e) => {
                  const r = (
                    e.currentTarget.ownerSVGElement as SVGSVGElement
                  ).getBoundingClientRect();
                  setHover({ t, x: e.clientX - r.left, y: e.clientY - r.top });
                }}
                onMouseLeave={() => setHover(null)}
              >
                <rect
                  x={0}
                  y={y}
                  width={width}
                  height={rowH}
                  fill={isSel ? "var(--surface-2)" : "transparent"}
                />
                <text
                  x={labelW - 8}
                  y={y + rowH / 2}
                  dy="0.32em"
                  textAnchor="end"
                  fontSize={11}
                  fill={isSel ? CHART.ink : CHART.ink2}
                  opacity={dim ? 0.55 : 1}
                >
                  {label.length > 34 ? `${label.slice(0, 33)}…` : label}
                </text>
                <rect
                  x={Math.min(x(0), x(t.nes))}
                  y={y + 4}
                  width={Math.abs(x(t.nes) - x(0))}
                  height={rowH - 8}
                  rx={2}
                  fill={t.nes > 0 ? CHART.case : CHART.control}
                  opacity={dim ? 0.35 : 1}
                />
                <text
                  x={t.nes > 0 ? x(t.nes) + 5 : x(0) + 5}
                  y={y + rowH / 2}
                  dy="0.32em"
                  textAnchor="start"
                  fontSize={10}
                  fill={CHART.ink3}
                >
                  {t.fdr < 0.001 ? "FDR <0.001" : `FDR ${fmtNum(t.fdr)}`}
                </text>
              </g>
            );
          })}
          <AxisBottom
            scale={x}
            y={height - m.bottom + 4}
            width={width}
            label="Normalized enrichment score"
          />
        </svg>
      )}
      {hover && (
        <ChartTip x={hover.x} y={hover.y} width={width}>
          <div className="font-medium">{hover.t.term}</div>
          <div>
            NES {fmtNum(hover.t.nes)} · FDR {fmtNum(hover.t.fdr, 3)} · {hover.t.size} genes
          </div>
          <div className="text-ink-3">click to highlight its leading genes on the volcano</div>
        </ChartTip>
      )}
      <div className="mt-2">
        <Legend
          items={[
            { label: "up in case", color: CHART.case },
            { label: "up in control", color: CHART.control },
          ]}
        />
      </div>
    </div>
  );
}

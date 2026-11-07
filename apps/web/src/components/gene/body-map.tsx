import { scaleLinear } from "d3-scale";
import { useEffect, useId, useMemo, useState } from "react";
import { Skeleton } from "@/components/ui/card";
import { ChartTip } from "@/components/ui/tooltip";
import { fmtNum } from "@/lib/format";
import {
  BODY_ORGANS,
  expressionRamp,
  type OrganValue,
  organForElementId,
  preferredSex,
  summariseByOrgan,
  unplacedTissues,
} from "@/lib/gene/body-map";
import { useSvgAsset } from "@/lib/gene/queries";
import { type GtexTissue, gtexTissueLabel } from "@/lib/gene/sources";
import { cssVar } from "@/lib/theme";
import { cn } from "@/lib/utils";
import { InlineSvg } from "./inline-svg";

type Sex = "male" | "female";

function rulesFor(scope: string, values: OrganValue[], color: (v: number) => string, max: number) {
  const lines: string[] = [];
  // every organ in the drawing gets a faint base so the figure reads as anatomy
  const all = BODY_ORGANS.flatMap((o) => o.ids).map((id) => `#${scope} #${id}, #${scope} #${id} *`);
  lines.push(
    `${all.join(", ")} { fill: var(--line-2) !important; fill-opacity: 0.45 !important; }`,
  );
  for (const v of values) {
    const c = color(expressionRamp(v.max, max));
    const sel = v.organ.ids.map((id) => `#${scope} #${id}, #${scope} #${id} *`).join(", ");
    lines.push(`${sel} { fill: ${c} !important; fill-opacity: 1 !important; }`);
  }
  return lines.join("\n");
}

export function BodyMap({ tissues, themeKey }: { tissues: GtexTissue[]; themeKey: string }) {
  const scope = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const values = useMemo(() => summariseByOrgan(tissues), [tissues]);
  const cells = useMemo(() => unplacedTissues(tissues), [tissues]);
  const [sex, setSex] = useState<Sex>(() => preferredSex(values));
  useEffect(() => setSex(preferredSex(values)), [values]);
  const asset = useSvgAsset(`/gene/body-${sex}.svg`);
  const [hover, setHover] = useState<{ v: OrganValue; x: number; y: number } | null>(null);
  const [frame, setFrame] = useState<{ w: number; h: number }>({ w: 0, h: 0 });

  const max = values[0]?.max ?? 0;
  // biome-ignore lint/correctness/useExhaustiveDependencies: themeKey re-reads the CSS variables
  const color = useMemo(
    () =>
      scaleLinear<string>()
        .domain([0, 1])
        .range([cssVar("--case-soft"), cssVar("--case")]),
    [themeKey],
  );
  const css = useMemo(() => rulesFor(scope, values, color, max), [scope, values, color, max]);

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setFrame({ w: r.width, h: r.height });
    let el = e.target as Element | null;
    while (el && el.tagName !== "svg") {
      const id = el.getAttribute("id");
      const organ = id ? organForElementId(id) : null;
      if (organ) {
        const v = values.find((x) => x.organ.key === organ.key);
        if (v) {
          setHover({ v, x: e.clientX - r.left, y: e.clientY - r.top });
          return;
        }
      }
      el = el.parentElement;
    }
    setHover(null);
  };

  const topTissues = useMemo(
    () => [...tissues].sort((a, b) => b.median - a.median).slice(0, 6),
    [tissues],
  );
  const hasSexSpecific = values.some((v) => v.organ.sex);

  return (
    <div>
      <style>{css}</style>
      <div className="grid gap-4 sm:grid-cols-[minmax(150px,200px)_1fr]">
        <div className="relative">
          {asset.isPending && <Skeleton className="aspect-[106/195] w-full" />}
          {asset.isError && (
            <p className="text-sm text-ink-3">The body drawing could not be loaded.</p>
          )}
          {asset.data && (
            <InlineSvg
              id={scope}
              svg={asset.data}
              role="img"
              aria-label={`Body map, ${sex} figure, darker organs express the gene more`}
              onMouseMove={onMove}
              onMouseLeave={() => setHover(null)}
            />
          )}
          {hover && (
            <ChartTip x={hover.x} y={hover.y} width={frame.w}>
              <div className="font-medium">{hover.v.organ.label}</div>
              {hover.v.tissues.map((t) => (
                <div key={t.id} className="num flex justify-between gap-3 text-ink-2">
                  <span>{gtexTissueLabel(t.id)}</span>
                  <span>{fmtNum(t.median, t.median < 10 ? 1 : 0)}</span>
                </div>
              ))}
            </ChartTip>
          )}
        </div>
        <div className="min-w-0">
          <div className="flex items-center justify-between gap-2">
            <div className="text-[12px] text-ink-3">Median TPM across GTEx donors</div>
            <div className="flex overflow-hidden rounded-md border border-line-2 text-[12px] font-semibold">
              {(["female", "male"] as const).map((s) => (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSex(s)}
                  aria-pressed={sex === s}
                  className={cn(
                    "h-[22px] px-2 capitalize",
                    sex === s ? "bg-accent-soft text-accent-ink" : "text-ink-3 hover:text-ink",
                  )}
                >
                  {s}
                </button>
              ))}
            </div>
          </div>
          <Ramp color={color} max={max} />
          <ol className="mt-3 space-y-1.5">
            {topTissues.map((t) => (
              <li key={t.id} className="text-[13px]">
                <div className="flex justify-between gap-2">
                  <span className="truncate">{gtexTissueLabel(t.id)}</span>
                  <span className="num shrink-0 text-ink-2">
                    {fmtNum(t.median, t.median < 10 ? 1 : 0)}
                  </span>
                </div>
                <div className="mt-0.5 h-1.5 w-full rounded-full bg-surface-2">
                  <div
                    className="h-1.5 rounded-full"
                    style={{
                      width: `${Math.max(2, (t.median / Math.max(max, topTissues[0]?.median ?? 1)) * 100)}%`,
                      background: color(expressionRamp(t.median, max)),
                    }}
                  />
                </div>
              </li>
            ))}
          </ol>
          {hasSexSpecific && (
            <p className="mt-2 text-[12px] text-ink-3">
              Switch the figure to see the other sex's organs.
            </p>
          )}
          {cells.length > 0 && (
            <p className="num mt-2 text-[12px] text-ink-3">
              Not on the body:{" "}
              {cells
                .map((c) => `${gtexTissueLabel(c.id)} ${fmtNum(c.median, c.median < 10 ? 1 : 0)}`)
                .join(" · ")}
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

function Ramp({ color, max }: { color: (v: number) => string; max: number }) {
  const stops = [0, 0.25, 0.5, 0.75, 1].map((v) => color(v)).join(", ");
  return (
    <div className="mt-2">
      <div
        className="h-2 w-full rounded-sm"
        style={{ background: `linear-gradient(90deg, ${stops})` }}
      />
      <div className="num mt-0.5 flex justify-between text-[11px] text-ink-3">
        <span>0</span>
        <span>log scale</span>
        <span>{fmtNum(max, max < 10 ? 1 : 0)} TPM</span>
      </div>
    </div>
  );
}

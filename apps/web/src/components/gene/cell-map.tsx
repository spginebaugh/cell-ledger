import { useId, useMemo, useState } from "react";
import { Skeleton } from "@/components/ui/card";
import { type CellHighlights, compartmentLabel } from "@/lib/gene/cell-map";
import { useSvgAsset } from "@/lib/gene/queries";
import { cn } from "@/lib/utils";
import { InlineSvg } from "./inline-svg";

/** The cytosol group covers the whole interior, so it gets a wash rather than a fill. */
const WASH = new Set(["cytosol", "secreted_proteins"]);

function rulesFor(scope: string, h: CellHighlights): string {
  const lines: string[] = [`#${scope} #cell_legend { display: none; }`];
  for (const [id, level] of h.byCompartment) {
    const opacity = WASH.has(id)
      ? level === "main"
        ? 0.28
        : 0.16
      : level === "main"
        ? 0.95
        : 0.45;
    lines.push(
      `#${scope} #${id}, #${scope} #${id} * { fill: var(--locus) !important; fill-opacity: ${opacity} !important; }`,
    );
  }
  return lines.join("\n");
}

export function CellMap({ highlights }: { highlights: CellHighlights }) {
  const scope = useId().replace(/[^a-zA-Z0-9_-]/g, "");
  const asset = useSvgAsset("/gene/cell.svg");
  const [hover, setHover] = useState<string | null>(null);
  const css = useMemo(() => rulesFor(scope, highlights), [scope, highlights]);

  const main = [...highlights.byCompartment].filter(([, l]) => l === "main").map(([id]) => id);
  const additional = [...highlights.byCompartment]
    .filter(([, l]) => l === "additional")
    .map(([id]) => id);

  const onMove = (e: React.MouseEvent<HTMLDivElement>) => {
    let el = e.target as Element | null;
    while (el && el.tagName !== "svg") {
      const id = el.getAttribute("id");
      if (id && highlights.byCompartment.has(id)) {
        setHover(id);
        return;
      }
      el = el.parentElement;
    }
    setHover(null);
  };

  return (
    <div>
      <style>{css}</style>
      {asset.isPending && <Skeleton className="aspect-[612/520] w-full" />}
      {asset.isError && <p className="text-sm text-ink-3">The cell drawing could not be loaded.</p>}
      {asset.data && (
        <InlineSvg
          id={scope}
          svg={asset.data}
          className="mx-auto max-w-[420px]"
          onMouseMove={onMove}
          onMouseLeave={() => setHover(null)}
          role="img"
          aria-label={`Cell drawing with ${[...highlights.byCompartment.keys()].map(compartmentLabel).join(", ")} highlighted`}
        />
      )}
      <div className="mt-2 min-h-[1.25rem] text-[12px] text-ink-3">
        {hover ? compartmentLabel(hover) : "Hover a highlighted compartment to name it."}
      </div>
      <dl className="mt-2 space-y-1.5 text-[13px]">
        {main.length > 0 && <LocRow label="Main" ids={main} strong />}
        {additional.length > 0 && <LocRow label="Also seen" ids={additional} />}
        {highlights.undrawn.length > 0 && (
          <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <dt className="text-ink-3">Not drawn</dt>
            <dd className="text-ink-2">{highlights.undrawn.join(", ")}</dd>
          </div>
        )}
      </dl>
    </div>
  );
}

function LocRow({ label, ids, strong }: { label: string; ids: string[]; strong?: boolean }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
      <dt className="text-ink-3">{label}</dt>
      <dd className="flex flex-wrap gap-1">
        {ids.map((id) => (
          <span
            key={id}
            className={cn(
              "inline-flex h-[22px] items-center gap-1.5 rounded-md border px-2 text-[12px] font-semibold",
              strong
                ? "border-locus/40 bg-locus-soft text-locus"
                : "border-line-2 bg-surface-2 text-ink-2",
            )}
          >
            <span
              className="inline-block h-2 w-2 rounded-full bg-locus"
              style={{ opacity: strong ? 1 : 0.45 }}
              aria-hidden
            />
            {compartmentLabel(id)}
          </span>
        ))}
      </dd>
    </div>
  );
}

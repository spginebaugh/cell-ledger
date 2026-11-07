import { useEffect, useRef, useState } from "react";
import { Skeleton } from "@/components/ui/card";
import { fmtNum, fmtPct } from "@/lib/format";
import { type AlphaFoldModel, alphaFoldPageUrl, PLDDT_BANDS, plddtColor } from "@/lib/gene/sources";
import { cssVar } from "@/lib/theme";
import { cn } from "@/lib/utils";

type Viewer = import("3dmol").GLViewer;

/** AlphaFold's predicted structure, drawn as a cartoon coloured by confidence (pLDDT). */
export function Structure({
  model,
  accession,
  themeKey,
}: {
  model: AlphaFoldModel;
  accession: string;
  themeKey: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<Viewer | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");
  const [spin, setSpin] = useState(
    () => !window.matchMedia?.("(prefers-reduced-motion: reduce)").matches,
  );

  // biome-ignore lint/correctness/useExhaustiveDependencies: a theme change re-creates the viewer so the canvas background follows it
  useEffect(() => {
    const el = host.current;
    if (!el) return;
    let cancelled = false;
    setState("loading");
    (async () => {
      try {
        const [$3Dmol, res] = await Promise.all([import("3dmol"), fetch(model.pdbUrl)]);
        if (!res.ok) throw new Error(`alphafold.ebi.ac.uk answered ${res.status}`);
        const pdb = await res.text();
        if (cancelled) return;
        el.replaceChildren();
        const v = $3Dmol.createViewer(el, {
          backgroundColor: cssVar("--surface") || "#ffffff",
          antialias: true,
        });
        v.addModel(pdb, "pdb");
        // AlphaFold writes pLDDT into the B-factor column.
        v.setStyle({}, { cartoon: { colorfunc: (atom: { b: number }) => plddtColor(atom.b) } });
        v.zoomTo();
        v.render();
        viewer.current = v;
        setState("ready");
      } catch {
        if (!cancelled) setState("error");
      }
    })();
    const ro = new ResizeObserver(() => viewer.current?.resize());
    ro.observe(el);
    return () => {
      cancelled = true;
      ro.disconnect();
      viewer.current?.spin(false);
      viewer.current?.clear();
      viewer.current = null;
      el.replaceChildren();
    };
  }, [model.pdbUrl, themeKey]);

  useEffect(() => {
    const v = viewer.current;
    if (!v || state !== "ready") return;
    if (spin) v.spin("y", 0.6);
    else v.spin(false);
  }, [spin, state]);

  return (
    <div>
      <div className="relative overflow-hidden rounded-md border border-line bg-surface">
        <div ref={host} className="h-[300px] w-full" role="img" aria-label="3D protein structure" />
        {state === "loading" && <Skeleton className="absolute inset-0 rounded-none" />}
        {state === "error" && (
          <p className="absolute inset-0 flex items-center justify-center p-4 text-center text-sm text-ink-3">
            The 3D structure could not be loaded.
          </p>
        )}
        {state === "ready" && (
          <button
            type="button"
            onClick={() => setSpin((s) => !s)}
            aria-pressed={spin}
            className={cn(
              "absolute right-2 top-2 rounded-md border border-line bg-surface px-2 py-0.5 text-[12px] text-ink-2 hover:text-ink",
            )}
          >
            {spin ? "Stop" : "Spin"}
          </button>
        )}
      </div>
      <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px] text-ink-2">
        {PLDDT_BANDS.map((b) => (
          <span key={b.label} className="inline-flex items-center gap-1">
            <span className="inline-block h-2.5 w-2.5 rounded-sm" style={{ background: b.color }} />
            {b.label}
          </span>
        ))}
      </div>
      <p className="num mt-1.5 text-[12px] text-ink-3">
        {model.length} residues · mean confidence {fmtNum(model.meanPlddt, 0)} ·{" "}
        {fmtPct(model.fractionVeryHigh + model.fractionConfident)} of the chain confident or better
        ·{" "}
        <a
          href={alphaFoldPageUrl(accession)}
          target="_blank"
          rel="noreferrer"
          className="underline"
        >
          AlphaFold DB
        </a>
      </p>
    </div>
  );
}

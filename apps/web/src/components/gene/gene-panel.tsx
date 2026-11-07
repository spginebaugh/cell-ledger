import { Dialog as RD } from "radix-ui";
import { type ReactNode, useMemo } from "react";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/card";
import { cellHighlightsFromHpa, cellHighlightsFromUniProt } from "@/lib/gene/cell-map";
import { useAlphaFold, useGeneCore, useGtex, useHpa, useUniProt } from "@/lib/gene/queries";
import {
  type GeneCore,
  gtexGeneUrl,
  hpaGeneUrl,
  ncbiGeneUrl,
  uniprotUrl,
} from "@/lib/gene/sources";
import { BodyMap } from "./body-map";
import { CellMap } from "./cell-map";
import { Network } from "./network";
import { Structure } from "./structure";

export type SelectedGene = {
  symbol: string;
  /** NCBI GeneID when known; otherwise the symbol is resolved. */
  entrez: string | null;
};

/** A side panel describing one human gene from public annotation sources only.
 *
 * Nothing here depends on the experiment the gene was selected from: the inputs are a
 * symbol and, when the caller has it, an NCBI GeneID.
 */
export function GenePanel({
  gene,
  onClose,
  onPick,
  canPick,
  themeKey,
}: {
  gene: SelectedGene | null;
  onClose: () => void;
  onPick?: (symbol: string) => void;
  canPick?: (symbol: string) => boolean;
  themeKey: string;
}) {
  return (
    <RD.Root open={gene !== null} onOpenChange={(o) => !o && onClose()} modal={false}>
      <RD.Portal>
        <RD.Content
          onInteractOutside={(e) => e.preventDefault()}
          className="fixed inset-y-0 right-0 z-50 flex w-[min(100vw,560px)] flex-col border-l border-line bg-surface shadow-2xl focus:outline-none"
          aria-describedby={undefined}
        >
          {gene && (
            <PanelBody
              key={gene.symbol}
              gene={gene}
              onPick={onPick}
              canPick={canPick}
              themeKey={themeKey}
            />
          )}
          <RD.Close asChild>
            <button
              type="button"
              aria-label="Close gene panel"
              className="absolute right-3 top-3 rounded-md px-2 py-1 text-ink-3 hover:bg-surface-2 hover:text-ink"
            >
              ×
            </button>
          </RD.Close>
        </RD.Content>
      </RD.Portal>
    </RD.Root>
  );
}

function PanelBody({
  gene,
  onPick,
  canPick,
  themeKey,
}: {
  gene: SelectedGene;
  onPick?: (symbol: string) => void;
  canPick?: (symbol: string) => boolean;
  themeKey: string;
}) {
  const core = useGeneCore(gene.entrez, gene.symbol);
  const g = core.data ?? null;
  const protein = g ? g.type === "protein-coding" || Boolean(g.uniprot) : false;
  const hpa = useHpa(g?.ensembl);
  const uniprot = useUniProt(g?.uniprot);
  const gtex = useGtex(gene.symbol);
  const alphafold = useAlphaFold(g?.uniprot);

  const cell = useMemo(() => {
    if (hpa.data && (hpa.data.mainLocations.length || hpa.data.additionalLocations.length))
      return cellHighlightsFromHpa(hpa.data.mainLocations, hpa.data.additionalLocations);
    if (uniprot.data?.locations.length) return cellHighlightsFromUniProt(uniprot.data.locations);
    return null;
  }, [hpa.data, uniprot.data]);

  const summary = g?.summary ?? uniprot.data?.functionText ?? null;
  const summarySource = g?.summary ? "NCBI Gene" : uniprot.data?.functionText ? "UniProt" : null;

  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <header className="border-b border-line px-5 pb-4 pt-5 pr-12">
        <RD.Title asChild>
          <h2 className="flex flex-wrap items-baseline gap-x-2">
            <span>{gene.symbol}</span>
            {g?.name && <span className="text-[0.95rem] font-normal text-ink-2">{g.name}</span>}
          </h2>
        </RD.Title>
        {core.isPending && <Skeleton className="mt-2 h-5 w-2/3" />}
        {core.isError && (
          <p className="mt-2 text-sm text-danger">
            Could not look this gene up: {(core.error as Error).message}
          </p>
        )}
        {g && <Facts g={g} evidence={hpa.data?.evidence ?? null} />}
      </header>

      <div className="space-y-7 px-5 py-5">
        <Section
          title="What it does"
          source={summarySource}
          pending={core.isPending || (protein && uniprot.isPending && !g?.summary)}
        >
          {summary ? (
            <p className="text-[14px] leading-relaxed text-ink">{summary}</p>
          ) : (
            g && (
              <p className="text-sm text-ink-3">No written summary is available for this gene.</p>
            )
          )}
        </Section>

        {(protein || hpa.isPending) && (
          <Section
            title="Where in the cell"
            source={cell?.source === "hpa" ? "Human Protein Atlas" : cell ? "UniProt" : null}
            pending={hpa.isPending || (!cell && uniprot.isPending)}
          >
            {cell ? (
              <CellMap highlights={cell} />
            ) : (
              <p className="text-sm text-ink-3">No subcellular location has been recorded.</p>
            )}
          </Section>
        )}

        <Section
          title="Where in the body"
          source={gtex.data ? "GTEx" : null}
          pending={gtex.isPending}
        >
          {gtex.isError && (
            <p className="text-sm text-ink-3">
              GTEx could not be reached: {(gtex.error as Error).message}
            </p>
          )}
          {gtex.isSuccess && gtex.data === null && (
            <p className="text-sm text-ink-3">GTEx has no expression data for this gene.</p>
          )}
          {gtex.data && <BodyMap tissues={gtex.data} themeKey={themeKey} />}
        </Section>

        {g?.uniprot && (
          <Section
            title="3D structure"
            source={alphafold.data ? "AlphaFold DB" : null}
            pending={alphafold.isPending}
          >
            {alphafold.isSuccess && alphafold.data === null && (
              <p className="text-sm text-ink-3">AlphaFold has no model for this protein.</p>
            )}
            {alphafold.isError && (
              <p className="text-sm text-ink-3">AlphaFold could not be reached.</p>
            )}
            {alphafold.data && (
              <Structure model={alphafold.data} accession={g.uniprot} themeKey={themeKey} />
            )}
          </Section>
        )}

        {protein && (
          <Section title="Interaction partners" source="STRING">
            <Network symbol={gene.symbol} onPick={onPick} canPick={canPick} />
          </Section>
        )}

        <Footer g={g} />
      </div>
    </div>
  );
}

function Facts({ g, evidence }: { g: GeneCore; evidence: string | null }) {
  return (
    <div className="mt-2 space-y-1.5 text-[13px]">
      <div className="flex flex-wrap gap-1.5">
        {g.type && <Badge>{g.type.replaceAll("-", " ")}</Badge>}
        {g.mapLocation && <Badge>chr {g.mapLocation}</Badge>}
        {evidence && (
          <Badge tone={evidence.includes("protein") ? "ok" : "neutral"}>{evidence}</Badge>
        )}
      </div>
      {g.aliases.length > 0 && (
        <p className="text-ink-2">
          <span className="text-ink-3">Also called</span> {g.aliases.slice(0, 8).join(", ")}
        </p>
      )}
    </div>
  );
}

function Section({
  title,
  source,
  pending,
  children,
}: {
  title: string;
  source?: string | null;
  pending?: boolean;
  children: ReactNode;
}) {
  return (
    <section>
      <div className="mb-2 flex items-baseline justify-between gap-2">
        <h3>{title}</h3>
        {source && <span className="text-[12px] text-ink-3">{source}</span>}
      </div>
      {pending ? <Skeleton className="h-24" /> : children}
    </section>
  );
}

function Footer({ g }: { g: GeneCore | null }) {
  if (!g) return null;
  const links: { label: string; href: string }[] = [
    { label: "NCBI Gene", href: ncbiGeneUrl(g.entrez) },
  ];
  if (g.ensembl)
    links.push({ label: "Human Protein Atlas", href: hpaGeneUrl(g.ensembl, g.symbol) });
  if (g.uniprot) links.push({ label: "UniProt", href: uniprotUrl(g.uniprot) });
  links.push({ label: "GTEx", href: gtexGeneUrl(g.symbol) });
  return (
    <footer className="border-t border-line pt-4 text-[12px] text-ink-3">
      <p>
        {links.map((l, i) => (
          <span key={l.href}>
            {i > 0 && " · "}
            <a href={l.href} target="_blank" rel="noreferrer" className="underline">
              {l.label}
            </a>
          </span>
        ))}
      </p>
      <p className="mt-1.5">
        Cell drawing from the Human Protein Atlas and body drawing from EMBL-EBI Expression Atlas,
        both CC BY 4.0. Expression is from GTEx, structure from AlphaFold DB, interactions from
        STRING. None of this comes from the dataset on this page.
      </p>
    </footer>
  );
}

import { X } from "lucide-react";
import { Dialog as RD } from "radix-ui";
import { type ReactNode, useMemo } from "react";
import { Badge, Tag } from "@/components/ui/badge";
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
              className="absolute right-4 top-4 inline-grid h-8 w-8 place-items-center rounded-md border border-line-2 bg-surface text-ink-2 hover:border-accent hover:text-accent-ink"
            >
              <X size={15} />
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
      <header className="border-b border-line px-5 pb-4 pr-14 pt-5">
        <Tag>Gene</Tag>
        <RD.Title asChild>
          <h2 className="mt-2 flex flex-wrap items-baseline gap-x-2 not-italic text-ink">
            <span
              className="font-display text-[30px] font-medium leading-none"
              style={{ fontVariationSettings: '"opsz" 48' }}
            >
              {gene.symbol}
            </span>
            {g?.name && (
              <span className="font-sans text-[14px] font-normal not-italic text-ink-2">
                {g.name}
              </span>
            )}
          </h2>
        </RD.Title>
        {core.isPending && <Skeleton className="mt-2 h-5 w-2/3" />}
        {core.isError && (
          <p className="mt-2 text-[13px] text-danger">
            Could not look this gene up: {(core.error as Error).message}
          </p>
        )}
        {g && <Facts g={g} evidence={hpa.data?.evidence ?? null} />}
      </header>

      <div className="space-y-6 px-5 py-5">
        <Section
          title="What it does"
          source={summarySource}
          pending={core.isPending || (protein && uniprot.isPending && !g?.summary)}
        >
          {summary ? (
            <p className="text-[14px] leading-relaxed text-ink">{summary}</p>
          ) : (
            g && (
              <p className="text-[13px] text-ink-3">
                No written summary is available for this gene.
              </p>
            )
          )}
        </Section>

        {g?.uniprot && (
          <Section
            title="3D structure"
            source={alphafold.data ? "AlphaFold DB" : null}
            pending={alphafold.isPending}
          >
            {alphafold.isSuccess && alphafold.data === null && (
              <p className="text-[13px] text-ink-3">AlphaFold has no model for this protein.</p>
            )}
            {alphafold.isError && (
              <p className="text-[13px] text-ink-3">AlphaFold could not be reached.</p>
            )}
            {alphafold.data && (
              <Structure model={alphafold.data} accession={g.uniprot} themeKey={themeKey} />
            )}
          </Section>
        )}

        <Section
          title="Where in the body"
          source={gtex.data ? "GTEx" : null}
          pending={gtex.isPending}
        >
          {gtex.isError && (
            <p className="text-[13px] text-ink-3">
              GTEx could not be reached: {(gtex.error as Error).message}
            </p>
          )}
          {gtex.isSuccess && gtex.data === null && (
            <p className="text-[13px] text-ink-3">GTEx has no expression data for this gene.</p>
          )}
          {gtex.data && <BodyMap tissues={gtex.data} themeKey={themeKey} />}
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
              <p className="text-[13px] text-ink-3">No subcellular location has been recorded.</p>
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
    <div className="mt-3 space-y-2 text-[13px]">
      <div className="flex flex-wrap gap-1.5">
        {g.type && <Badge>{g.type.replaceAll("-", " ")}</Badge>}
        {g.mapLocation && <Badge className="font-mono normal-case">chr {g.mapLocation}</Badge>}
        {evidence && (
          <Badge tone={evidence.includes("protein") ? "ok" : "neutral"}>{evidence}</Badge>
        )}
      </div>
      {g.aliases.length > 0 && (
        <p className="text-ink-2">
          <span className="text-ink-3">Also called</span>{" "}
          <span className="font-mono text-[12px]">{g.aliases.slice(0, 8).join(", ")}</span>
        </p>
      )}
    </div>
  );
}

/** One block of the panel: a column-style label, the source on the right, a hairline above. */
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
    <section className="border-t border-line pt-4 first:border-t-0 first:pt-0">
      <div className="mb-3 flex items-center justify-between gap-2">
        <Tag>{title}</Tag>
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
      <ul className="flex flex-wrap">
        {links.map((l, i) => (
          <li key={l.href} className={i > 0 ? "border-l border-line-2 pl-3 ml-3" : ""}>
            <a
              href={l.href}
              target="_blank"
              rel="noreferrer"
              className="text-accent-ink no-underline hover:underline"
            >
              {l.label}
            </a>
          </li>
        ))}
      </ul>
      <p className="mt-2">
        Cell drawing from the Human Protein Atlas and body drawing from EMBL-EBI Expression Atlas,
        both CC BY 4.0. Expression is from GTEx, structure from AlphaFold DB, interactions from
        STRING. None of this comes from the dataset on this page.
      </p>
    </footer>
  );
}

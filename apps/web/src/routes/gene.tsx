import { Link, useNavigate } from "@tanstack/react-router";
import { ChevronLeft } from "lucide-react";
import { useEffect } from "react";
import { GenePanel } from "@/components/gene/gene-panel";
import { Footer, Page, TopBar } from "@/components/layout/top-bar";
import { useTheme } from "@/lib/theme";
import { geneRoute } from "@/router";

/** A gene on its own, outside any run: the same panel, addressed by symbol. */
export function GenePage() {
  const { symbol } = geneRoute.useParams();
  const navigate = useNavigate();
  const { resolved } = useTheme();
  useEffect(() => {
    document.title = `${symbol} · cell ledger`;
  }, [symbol]);
  return (
    <>
      <TopBar />
      <GenePanel
        gene={{ symbol, entrez: null }}
        onClose={() => navigate({ to: "/" })}
        themeKey={resolved}
      />
      <Page>
        <div className="flex items-center justify-between gap-2 text-[13px]">
          <Link
            to="/"
            className="inline-flex items-center gap-0.5 font-semibold text-ink no-underline hover:text-accent-ink"
          >
            <ChevronLeft size={14} strokeWidth={2.5} />
            Back
          </Link>
          <span className="font-semibold">
            Gene <span className="accession font-bold text-accent-ink">{symbol}</span>
          </span>
        </div>
        <h1 className="mt-3">{symbol}</h1>
        <p className="mt-3 max-w-[60ch] text-[13px] text-ink-2">
          Public annotation for this gene, independent of any dataset. Close the panel to return to
          the start page.
        </p>
        <Footer />
      </Page>
    </>
  );
}

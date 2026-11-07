import { useNavigate } from "@tanstack/react-router";
import { useEffect } from "react";
import { GenePanel } from "@/components/gene/gene-panel";
import { Page, TopBar } from "@/components/layout/top-bar";
import { useTheme } from "@/lib/theme";
import { geneRoute } from "@/router";

/** A gene on its own, outside any run: the same panel, addressed by symbol. */
export function GenePage() {
  const { symbol } = geneRoute.useParams();
  const navigate = useNavigate();
  const { resolved } = useTheme();
  useEffect(() => {
    document.title = `${symbol} · cell-ledger`;
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
        <p className="mt-6 max-w-[60ch] text-sm text-ink-2">
          Public annotation for <span className="font-medium text-ink">{symbol}</span>, independent
          of any dataset. Close the panel to return to the start page.
        </p>
      </Page>
    </>
  );
}

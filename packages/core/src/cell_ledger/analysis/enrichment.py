"""Gene set enrichment (GSEA preranked on the Wald statistic) with gseapy.

Ships MSigDB Hallmark (2020, via Enrichr) so the step works offline. Any GMT path
can be passed instead.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path
from typing import Any, cast

import pandas as pd
from pydantic import BaseModel, Field

from cell_ledger.report.models import EnrichmentSummary, EnrichmentTerm

HALLMARK = "msigdb_hallmark_2020"


class EnrichmentParams(BaseModel):
    gene_sets: str = HALLMARK
    permutation_num: int = Field(default=1000, ge=10)
    min_size: int = 15
    max_size: int = 500
    seed: int = 0
    threads: int = 4
    top_n: int = 20
    fdr_threshold: float = 0.25


def resolve_gene_sets(name_or_path: str) -> Path:
    if name_or_path == HALLMARK:
        return Path(str(files("cell_ledger.analysis.resources") / f"{HALLMARK}.gmt"))
    path = Path(name_or_path)
    if not path.exists():
        raise FileNotFoundError(f"gene set file not found: {name_or_path}")
    return path


def rank_by_stat(results: pd.DataFrame) -> pd.Series:
    """Symbol -> Wald statistic, one row per symbol (largest |stat| wins), sorted descending."""
    df = pd.DataFrame(results.loc[:, ["symbol", "stat"]]).dropna()
    symbols = df["symbol"].astype(str)
    df = pd.DataFrame(df.loc[symbols != ""])
    df["symbol"] = df["symbol"].astype(str).str.upper()
    df["abs"] = df["stat"].astype(float).abs()
    df = df.sort_values("abs", ascending=False).drop_duplicates("symbol")
    ranked = pd.Series(df.set_index("symbol")["stat"].astype(float))
    return ranked.sort_values(ascending=False)


def run_prerank(
    results: pd.DataFrame, params: EnrichmentParams
) -> tuple[pd.DataFrame, EnrichmentSummary]:
    import gseapy

    gmt = resolve_gene_sets(params.gene_sets)
    rnk = rank_by_stat(results)
    pre = gseapy.prerank(
        rnk=rnk,
        gene_sets=str(gmt),
        permutation_num=params.permutation_num,
        min_size=params.min_size,
        max_size=params.max_size,
        seed=params.seed,
        threads=params.threads,
        outdir=None,
        verbose=False,
    )
    if pre.res2d is None:
        raise RuntimeError("gseapy returned no results")
    df = pd.DataFrame(pre.res2d)
    df["NES"] = pd.to_numeric(df["NES"])
    df["NOM p-val"] = pd.to_numeric(df["NOM p-val"])
    df["FDR q-val"] = pd.to_numeric(df["FDR q-val"])
    df["size"] = df["Tag %"].astype(str).str.split("/").str[-1].astype(int)
    df["abs_nes"] = df["NES"].abs()
    df = df.sort_values(["FDR q-val", "abs_nes"], ascending=[True, False]).drop(columns="abs_nes")
    top: list[EnrichmentTerm] = []
    for _, row in df.head(params.top_n).iterrows():
        r = cast(Any, row)
        top.append(
            EnrichmentTerm(
                term=str(r["Term"]),
                nes=float(r["NES"]),
                pvalue=float(r["NOM p-val"]),
                fdr=float(r["FDR q-val"]),
                size=int(r["size"]),
                lead_genes=str(r["Lead_genes"]).split(";")[:10],
            )
        )
    summary = EnrichmentSummary(
        library=gmt.stem,
        n_terms=len(df),
        n_sig_fdr=int(cast(Any, df["FDR q-val"] < params.fdr_threshold).sum()),
        fdr_threshold=params.fdr_threshold,
        top=top,
        params=params.model_dump(),
    )
    return df, summary

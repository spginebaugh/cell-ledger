"""Two-group differential expression with pydeseq2 on the contrast samples only."""

from __future__ import annotations

from typing import Any, cast

import anndata as ad
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

from cell_ledger.analysis.bundle import obs_frame, var_frame
from cell_ledger.report.models import DeResultSummary, DeSummary, GeneRow

ARM = "arm"
DESIGN = "~arm"
COEFFICIENT = "arm[T.case]"
RESULT_COLUMNS = {
    "baseMean": "base_mean",
    "log2FoldChange": "log2fc",
    "lfcSE": "lfc_se",
    "stat": "stat",
    "pvalue": "pvalue",
    "padj": "padj",
}


class DeParams(BaseModel):
    alpha: float = Field(default=0.05, gt=0, lt=1)
    lfc_threshold: float = Field(default=1.0, ge=0)
    lfc_shrink: bool = True
    n_cpus: int | None = None
    top_n: int = 50


def run_de(
    adata: ad.AnnData, params: DeParams
) -> tuple[pd.DataFrame, pd.DataFrame, DeResultSummary]:
    """Returns (results by gene, size-factor normalized counts samples x genes, summary).

    ``adata`` must hold only case and control samples with an ``arm`` column; the
    reference level is forced to ``control`` so a positive log2FC means higher in case.
    """
    arms = [str(a) for a in obs_frame(adata)[ARM]]
    if set(arms) != {"case", "control"}:
        raise ValueError(f"DE needs exactly the arms case and control, got {sorted(set(arms))}")
    counts = pd.DataFrame(
        np.asarray(adata.layers["counts"], dtype=np.int64),
        index=adata.obs_names,
        columns=adata.var_names,
    )
    metadata = pd.DataFrame(
        {ARM: pd.Categorical(arms, categories=["control", "case"])}, index=adata.obs_names
    )
    dds = DeseqDataSet(
        counts=counts, metadata=metadata, design=DESIGN, quiet=True, n_cpus=params.n_cpus
    )
    dds.deseq2()
    stats = DeseqStats(dds, contrast=[ARM, "case", "control"], alpha=params.alpha, quiet=True)
    stats.summary()
    results = stats.results_df.copy()
    results["log2fc_unshrunk"] = results["log2FoldChange"]
    shrunk = False
    design_matrix = cast(pd.DataFrame, dds.obsm["design_matrix"])
    if params.lfc_shrink and COEFFICIENT in design_matrix.columns:
        stats.lfc_shrink(coeff=COEFFICIENT)
        results["log2FoldChange"] = stats.results_df["log2FoldChange"]
        results["lfcSE"] = stats.results_df["lfcSE"]
        shrunk = True

    results = results.rename(columns=RESULT_COLUMNS)
    results.index = results.index.astype(str)
    results.index.name = "gene_id"
    var = var_frame(adata)
    symbols = var["Symbol"] if "Symbol" in var.columns else pd.Series("", index=adata.var_names)
    results.insert(0, "symbol", symbols.reindex(results.index).fillna("").astype(str).to_numpy())
    results = results.sort_values(["padj", "pvalue"], na_position="last")

    normed = pd.DataFrame(
        np.asarray(dds.layers["normed_counts"]), index=adata.obs_names, columns=adata.var_names
    )

    sig = cast(pd.Series, results["padj"] < params.alpha)
    up = cast(pd.Series, sig & (results["log2fc"] > 0))
    down = cast(pd.Series, sig & (results["log2fc"] < 0))
    summary = DeSummary(
        design=DESIGN,
        coefficient=COEFFICIENT,
        lfc_shrunk=shrunk,
        alpha=params.alpha,
        lfc_threshold=params.lfc_threshold,
        n_genes_tested=_count(results["pvalue"].notna()),
        n_sig=_count(sig),
        n_up=_count(up),
        n_down=_count(down),
        n_up_lfc=_count(up & (results["log2fc"] >= params.lfc_threshold)),
        n_down_lfc=_count(down & (results["log2fc"] <= -params.lfc_threshold)),
    )
    return (
        results,
        normed,
        DeResultSummary(
            summary=summary,
            top_up=gene_rows(pd.DataFrame(results.loc[up]).head(params.top_n)),
            top_down=gene_rows(pd.DataFrame(results.loc[down]).head(params.top_n)),
        ),
    )


def _count(mask: object) -> int:
    return int(cast(Any, mask).sum())


def _opt(value: object) -> float | None:
    if value is None:
        return None
    v = float(cast(Any, value))
    return None if np.isnan(v) else v


def gene_rows(df: pd.DataFrame) -> list[GeneRow]:
    rows: list[GeneRow] = []
    for gid, row in df.iterrows():
        r = cast(Any, row)
        rows.append(
            GeneRow(
                gene_id=str(gid),
                symbol=(str(r["symbol"]) or None) if "symbol" in df.columns else None,
                base_mean=float(r["base_mean"]),
                log2fc=float(r["log2fc"]),
                lfc_se=_opt(r.get("lfc_se")),
                stat=_opt(r.get("stat")),
                pvalue=_opt(r.get("pvalue")),
                padj=_opt(r.get("padj")),
            )
        )
    return rows

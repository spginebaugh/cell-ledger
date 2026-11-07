"""Low-count gene filter in the spirit of edgeR's filterByExpr."""

from __future__ import annotations

import anndata as ad
import numpy as np

from cell_ledger.analysis.bundle import obs_frame
from cell_ledger.report.models import FilterSummary


def filter_genes(
    adata: ad.AnnData, *, min_count: int = 10, min_samples: int | None = None
) -> tuple[ad.AnnData, FilterSummary]:
    """Keep genes with at least ``min_count`` reads in at least ``min_samples`` samples.

    ``min_samples`` defaults to the size of the smallest arm so a gene expressed in
    only one arm survives.
    """
    counts = np.asarray(adata.layers["counts"])
    if min_samples is None:
        obs = obs_frame(adata)
        has_arms = "arm" in obs.columns
        min_samples = int(obs["arm"].value_counts().min()) if has_arms else adata.n_obs
    keep = (counts >= min_count).sum(axis=0) >= min_samples
    out = adata[:, keep].copy()
    return out, FilterSummary(
        n_genes_before=adata.n_vars,
        n_genes_after=out.n_vars,
        min_count=min_count,
        min_samples=min_samples,
    )

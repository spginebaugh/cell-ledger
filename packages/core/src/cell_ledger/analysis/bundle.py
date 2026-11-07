"""Turn a counts file, the annotation and a SampleSheet + Contrast into one AnnData.

Only the GSMs named by the contrast are kept. Columns are matched to GSMs by exact
identifier, never by order, and every mismatch is reported in ``Reconciliation``.
"""

from __future__ import annotations

from pathlib import Path
from typing import cast

import anndata as ad
import numpy as np
import pandas as pd

from cell_ledger.report.models import Reconciliation
from cell_ledger.samplesheet import Contrast, Group, SampleSheet

NUMERIC_OBS = {"confidence", "replicate"}
BOOL_OBS = {"needs_review"}


def obs_frame(adata: ad.AnnData) -> pd.DataFrame:
    """``adata.obs`` as a plain DataFrame (anndata types it as a union)."""
    return cast(pd.DataFrame, adata.obs)


def var_frame(adata: ad.AnnData) -> pd.DataFrame:
    return cast(pd.DataFrame, adata.var)


def load_counts(path: str | Path) -> pd.DataFrame:
    """Genes x samples integer matrix. Raises on anything that is not non-negative integers."""
    df = pd.read_csv(path, sep="\t", index_col=0)
    df.index = df.index.astype(str)
    df.columns = [str(c) for c in df.columns]
    if df.isna().any().any():
        raise ValueError(f"{path}: counts contain missing values")
    if not all(np.issubdtype(dt, np.integer) for dt in df.dtypes):
        bad = [c for c, dt in df.dtypes.items() if not np.issubdtype(dt, np.integer)]
        raise ValueError(f"{path}: non-integer columns (not raw counts?): {bad[:5]}")
    if (df.to_numpy() < 0).any():
        raise ValueError(f"{path}: negative counts")
    if df.index.duplicated().any():
        raise ValueError(f"{path}: duplicated gene identifiers")
    return df.astype(np.int64)


def _clean_obs(obs: pd.DataFrame) -> pd.DataFrame:
    """Make the per-sample frame h5ad-safe: strings for text, floats/bools elsewhere."""
    out = obs.copy()
    for col in out.columns:
        if col in NUMERIC_OBS:
            out[col] = pd.Series(
                pd.to_numeric(out[col], errors="coerce"), index=out.index, dtype=float
            )
        elif col in BOOL_OBS:
            out[col] = out[col].fillna(False).astype(bool)
        else:
            out[col] = pd.Series(
                ["" if v is None or v is pd.NA else str(v) for v in out[col]],
                index=out.index,
                dtype=str,
            )
    return out


def build_anndata(
    counts: pd.DataFrame,
    sheet: SampleSheet,
    annotation: pd.DataFrame,
    contrast: Contrast,
) -> tuple[ad.AnnData, Reconciliation]:
    columns = list(counts.columns)
    col_set = set(columns)
    sheet_set = set(sheet.gsms)
    used = [g for g in contrast.gsms if g in col_set and g in sheet_set]
    arms = [contrast.arm_of(g) for g in used]

    obs = _clean_obs(sheet.subset(used).to_dataframe().loc[used])
    obs["arm"] = [a.value for a in arms]
    var = annotation.reindex(counts.index)
    var.index = counts.index.astype(str)
    var.index.name = "gene_id"

    x = counts[used].T.to_numpy(dtype=np.int64)
    adata = ad.AnnData(X=x.astype(np.float64), obs=obs, var=var)
    adata.layers["counts"] = x
    adata.uns["gse"] = sheet.gse
    adata.uns["contrast"] = contrast.model_dump_json()

    rec = Reconciliation(
        n_counts_columns=len(columns),
        n_sheet_gsms=len(sheet.gsms),
        n_contrast_gsms=len(contrast.gsms),
        gsms_used=used,
        contrast_gsms_missing_from_counts=[g for g in contrast.gsms if g not in col_set],
        contrast_gsms_missing_from_sheet=[g for g in contrast.gsms if g not in sheet_set],
        sheet_gsms_missing_from_counts=[g for g in sheet.gsms if g not in col_set],
        columns_not_in_sheet=[c for c in columns if c not in sheet_set],
        n_genes=int(counts.shape[0]),
        n_case=sum(a is Group.CASE for a in arms),
        n_control=sum(a is Group.CONTROL for a in arms),
    )
    return adata, rec

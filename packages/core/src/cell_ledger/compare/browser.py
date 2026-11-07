"""The cross-dataset gene table the browser draws (``pooled_genes.json.gz``).

One row per pooled gene, column-major, with every dataset's own estimate beside the pooled
one so the browser can draw the pooled volcano, the genome-wide agreement wall and a forest
plot for any gene without another request. Values are quantised to what a plot can show
(fold changes and standard errors to 0.01, ``-log10 padj`` to 0.1); the full-precision table
stays in ``gene_table.tsv``.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from cell_ledger.compare.meta import EffectMatrices

POOLED_GENES_FILE = "pooled_genes.json.gz"
LFC_SCALE = 100
NLP_SCALE = 10
NLP_CAP = 300 * NLP_SCALE  # padj underflows to 0 for the strongest genes; -log10 pinned at 300


def _ints(values: np.ndarray, scale: int) -> list[int | None]:
    out: list[int | None] = []
    for v in values.tolist():
        out.append(None if v is None or not np.isfinite(v) else round(v * scale))
    return out


def _neg_log_padj(padj: np.ndarray) -> list[int | None]:
    out: list[int | None] = []
    for p in padj.tolist():
        if p is None or not np.isfinite(p):
            out.append(None)
        else:
            out.append(min(NLP_CAP, round(-np.log10(max(p, 1e-300)) * NLP_SCALE)))
    return out


def write_pooled_genes(
    table: pd.DataFrame,
    m: EffectMatrices,
    path: Path,
    *,
    pooled: Sequence[str],
    flags: Mapping[str, Sequence[str]],
    alpha: float,
    lfc_threshold: float,
    min_studies: int,
) -> int:
    """Write the file; returns the number of genes written.

    ``table`` is the gene table over the pooled datasets; ``m`` holds every included dataset
    (pooled or set aside) so the set-aside ones can be drawn beside the pool. Only genes with
    a pooled estimate are written.
    """
    has_pooled = cast(pd.Series, table["pooled_log2fc"]).notna().to_numpy()
    keep = table.index[has_pooled]
    t = table.loc[keep]
    order = [*pooled, *(lab for lab in m.labels if lab not in set(pooled))]
    lfc = m.lfc.reindex(index=keep, columns=order)
    se = m.se.reindex(index=keep, columns=order)
    padj = m.padj.reindex(index=keep, columns=order)
    tested = lfc.notna() & se.notna() & (se > 0)
    sig = tested & padj.notna() & (padj < alpha)
    lfc_v = lfc.to_numpy(dtype=float, copy=True)
    se_v = se.to_numpy(dtype=float, copy=True)
    lfc_v[~tested.to_numpy()] = np.nan
    se_v[~tested.to_numpy()] = np.nan

    n_tested = t["n_tested"].to_numpy(dtype=float)
    n_sig_dir = np.rint(t["replication"].to_numpy(dtype=float) * n_tested)
    doc: dict[str, Any] = {
        "n": len(keep),
        "alpha": alpha,
        "lfc_threshold": lfc_threshold,
        "min_studies": min_studies,
        "lfc_scale": LFC_SCALE,
        "nlp_scale": NLP_SCALE,
        "members": [
            {
                "label": lab,
                "gse": lab.split(":")[0],
                "pooled": lab in set(pooled),
                "flags": list(flags.get(lab, [])),
                "n_samples": int(m.n_samples.get(lab, 0) or 0),
            }
            for lab in order
        ],
        "gene_id": [str(g) for g in keep.tolist()],
        "symbol": [s or None for s in t["symbol"].astype(str).tolist()],
        "log2fc": _ints(t["pooled_log2fc"].to_numpy(dtype=float), LFC_SCALE),
        "nlp": _neg_log_padj(t["padj"].to_numpy(dtype=float)),
        "n_tested": [int(v) for v in n_tested.tolist()],
        "n_agree": [int(v) for v in t["n_agree_pooled"].tolist()],
        "n_sig": [int(v) for v in n_sig_dir.tolist()],
        "robust": [int(bool(v)) for v in t["robust"].tolist()],
        "member_lfc": [_ints(lfc_v[:, j], LFC_SCALE) for j in range(len(order))],
        "member_se": [_ints(se_v[:, j], LFC_SCALE) for j in range(len(order))],
        "member_sig": [[int(v) for v in sig.iloc[:, j].tolist()] for j in range(len(order))],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    return len(keep)

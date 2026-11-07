"""Cross-dataset figures: concordance heatmap, pathway NES heatmap, per-gene forest plots."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.colors import TwoSlopeNorm

from cell_ledger.compare.models import Concordance, GeneLookupAcross, PathwaySynthesis
from cell_ledger.report.figures import CASE, CONTROL, INK, INK2, MUTED, _save, _style


def _short(label: str) -> str:
    return label.split(":")[0]


def concordance_heatmap(conc: Concordance, path: Path, flags: Mapping[str, Sequence[str]]) -> Path:
    k = len(conc.members)
    mat = np.array([[np.nan if v is None else v for v in row] for row in conc.spearman])
    fig, ax = plt.subplots(figsize=(max(4, 0.45 * k + 2), max(3.5, 0.45 * k + 1.5)))
    im = ax.imshow(mat, cmap="RdBu_r", norm=TwoSlopeNorm(vcenter=0, vmin=-1, vmax=1))
    ax.set_xticks(range(k))
    ax.set_yticks(range(k))
    labels = [
        _short(m) + (f" ({', '.join(flags[m])})" if flags.get(m) else "") for m in conc.members
    ]
    ax.set_xticklabels(labels, rotation=90, fontsize=7, color=INK2)
    ax.set_yticklabels(labels, fontsize=7, color=INK2)
    for i in range(k):
        for j in range(k):
            if i != j and np.isfinite(mat[i, j]):
                ax.text(j, i, f"{mat[i, j]:.2f}", ha="center", va="center", fontsize=6, color=INK)
    ax.set_title("Spearman correlation of Wald statistics (shared genes)", fontsize=10, loc="left")
    fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02).ax.tick_params(labelsize=7)
    return _save(fig, path)


def nes_heatmap(pathways: PathwaySynthesis, path: Path, n_terms: int = 50) -> Path | None:
    terms = pathways.terms[:n_terms]
    if not terms:
        return None
    members = sorted({m for t in terms for m in t.nes})
    if not members:
        return None
    terms = sorted(terms, key=lambda t: t.mean_nes)
    mat = np.array([[t.nes.get(m, np.nan) for m in members] for t in terms])
    fig, ax = plt.subplots(figsize=(max(4, 0.4 * len(members) + 3), 0.22 * len(terms) + 1.5))
    lim = float(np.nanmax(np.abs(mat))) if np.isfinite(mat).any() else 1.0
    im = ax.imshow(
        mat, cmap="RdBu_r", norm=TwoSlopeNorm(vcenter=0, vmin=-lim, vmax=lim), aspect="auto"
    )
    ax.set_xticks(range(len(members)))
    ax.set_xticklabels([_short(m) for m in members], rotation=90, fontsize=7, color=INK2)
    ax.set_yticks(range(len(terms)))
    ax.set_yticklabels(
        [f"{t.term}  ({t.n_pos}+/{t.n_neg}-)" for t in terms], fontsize=6.5, color=INK2
    )
    for i, t in enumerate(terms):
        for j, m in enumerate(members):
            if t.fdr.get(m, 1.0) < pathways.fdr_threshold:
                ax.text(j, i, "•", ha="center", va="center", fontsize=6, color=INK)
    ax.set_title(
        f"GSEA NES per dataset, {pathways.library} (dot: FDR < {pathways.fdr_threshold})",
        fontsize=10,
        loc="left",
    )
    fig.colorbar(im, ax=ax, fraction=0.03, pad=0.02).ax.tick_params(labelsize=7)
    return _save(fig, path)


def forest(
    lookups: list[GeneLookupAcross],
    lfc: pd.DataFrame,
    se: pd.DataFrame,
    path: Path,
    max_genes: int = 12,
) -> Path | None:
    rows = [r for r in lookups if r.gene_id is not None and r.gene_id in lfc.index][:max_genes]
    if not rows:
        return None
    members = list(lfc.columns)
    cols = min(3, len(rows))
    nrows = int(np.ceil(len(rows) / cols))
    fig, axes = plt.subplots(
        nrows, cols, figsize=(3.4 * cols, (0.22 * len(members) + 1.2) * nrows), squeeze=False
    )
    for ax, row in zip(axes.flat, rows, strict=False):
        _style(ax)
        ax.grid(True, axis="x", color="#e6e5e1", linewidth=0.6)
        ax.grid(False, axis="y")
        y_pos = np.arange(len(members))
        est = lfc.loc[row.gene_id, members].to_numpy(dtype=float)
        err = 1.96 * se.loc[row.gene_id, members].to_numpy(dtype=float)
        for y, e, w in zip(y_pos, est, err, strict=True):
            if np.isnan(e):
                ax.scatter([0], [y], marker="x", s=14, color=MUTED, linewidths=1)
                continue
            color = CASE if e > 0 else CONTROL
            ax.errorbar(e, y, xerr=w, fmt="o", color=color, ms=4, elinewidth=1, capsize=0)
        if row.meta and row.meta.pooled_log2fc is not None:
            p, lo, hi = row.meta.pooled_log2fc, row.meta.ci_low or 0.0, row.meta.ci_high or 0.0
            yp = len(members) + 0.6
            ax.fill([lo, p, hi, p], [yp, yp + 0.35, yp, yp - 0.35], color=INK, alpha=0.85, zorder=4)
            ax.set_ylim(-0.8, yp + 0.9)
        ax.axvline(0, color=INK2, linewidth=0.8)
        ax.set_yticks(list(y_pos) + ([len(members) + 0.6] if row.meta else []))
        ax.set_yticklabels(
            [_short(m) for m in members] + (["pooled"] if row.meta else []), fontsize=6.5
        )
        ax.set_xlabel("log2FC (95% CI)", fontsize=7)
        title = f"{row.symbol or row.gene_id}: {row.verdict.replace('_', ' ')}"
        if row.meta and row.meta.i2 is not None:
            title += f"  I²={row.meta.i2:.2f}"
        ax.set_title(title, fontsize=8, loc="left")
    for ax in list(axes.flat)[len(rows) :]:
        ax.axis("off")
    fig.tight_layout()
    return _save(fig, path)

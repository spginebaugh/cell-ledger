"""Static QC and DE figures (matplotlib, Agg). Case is blue, control is orange, everywhere."""

from __future__ import annotations

from pathlib import Path
from typing import Any, cast

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.axes import Axes
from matplotlib.figure import Figure
from matplotlib.lines import Line2D

from cell_ledger.report.models import EnrichmentSummary, GeneLookupRow, QcResult

CASE = "#2a78d6"
CONTROL = "#eb6834"
MUTED = "#b8b7b2"
INK = "#0b0b0b"
INK2 = "#52514e"
SURFACE = "#fcfcfb"
ARM_COLOR = {"case": CASE, "control": CONTROL}


def _style(ax: Axes) -> None:
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK2)
        ax.spines[side].set_linewidth(0.8)
    ax.tick_params(colors=INK2, labelsize=8)
    ax.yaxis.label.set_color(INK2)
    ax.xaxis.label.set_color(INK2)
    ax.title.set_color(INK)
    ax.grid(True, axis="both", color="#e6e5e1", linewidth=0.6)
    ax.set_axisbelow(True)


def _save(fig: Figure, path: Path) -> Path:
    fig.patch.set_facecolor(SURFACE)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return path


def _legend(ax: Axes, labels: dict[str, str]) -> None:
    handles = [
        Line2D([], [], marker="o", linestyle="", color=c, markersize=7, label=lab)
        for lab, c in labels.items()
    ]
    ax.legend(handles=handles, frameon=False, fontsize=8, labelcolor=INK2)


def library_sizes(qc: QcResult, path: Path, low_library_size: float = 1e6) -> Path:
    rows = sorted(qc.samples, key=lambda s: s.library_size)
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.28 * len(rows) + 1)))
    _style(ax)
    y = np.arange(len(rows))
    ax.barh(
        y,
        [s.library_size / 1e6 for s in rows],
        color=[ARM_COLOR.get(s.arm, MUTED) for s in rows],
        height=0.7,
    )
    ax.set_yticks(y)
    ax.set_yticklabels([s.gsm for s in rows], fontsize=7)
    ax.axvline(low_library_size / 1e6, color=INK2, linestyle=":", linewidth=1)
    ax.set_xlabel("Library size (millions of assigned reads)")
    ax.set_title("Library size per sample", fontsize=10, loc="left")
    _legend(ax, {"case": CASE, "control": CONTROL})
    return _save(fig, path)


def pca(qc: QcResult, path: Path) -> Path:
    if qc.pca is None:
        raise ValueError("no PCA in QC result")
    fig, ax = plt.subplots(figsize=(6, 5))
    _style(ax)
    arm_of = {s.gsm: s.arm for s in qc.samples}
    flagged = {s.gsm for s in qc.samples if s.flags}
    for gsm, (x, y) in qc.pca.coords.items():
        ax.scatter(
            x,
            y,
            s=48,
            color=ARM_COLOR.get(arm_of.get(gsm, ""), MUTED),
            edgecolors=SURFACE,
            linewidths=1.5,
            zorder=3,
        )
        if gsm in flagged:
            ax.annotate(
                gsm, (x, y), fontsize=6, color=INK2, xytext=(4, 4), textcoords="offset points"
            )
    vr = qc.pca.variance_ratio
    ax.set_xlabel(f"PC1 ({vr[0] * 100:.0f}% of variance)")
    ax.set_ylabel(f"PC2 ({vr[1] * 100:.0f}% of variance)")
    ax.set_title(
        "PCA of log-CPM, top variable genes (flagged samples labelled)", fontsize=10, loc="left"
    )
    _legend(ax, {"case": CASE, "control": CONTROL})
    return _save(fig, path)


def volcano(
    results: pd.DataFrame, path: Path, *, alpha: float, lfc_threshold: float, n_labels: int = 12
) -> Path:
    df = results.dropna(subset=["padj", "log2fc"]).copy()
    df["neglog"] = -np.log10(df["padj"].clip(lower=1e-300))
    sig = cast(pd.Series, df["padj"] < alpha)
    up = cast(pd.Series, sig & (df["log2fc"] > 0))
    down = cast(pd.Series, sig & (df["log2fc"] < 0))
    fig, ax = plt.subplots(figsize=(6.5, 5))
    _style(ax)
    ax.scatter(
        df.loc[~sig, "log2fc"], df.loc[~sig, "neglog"], s=6, color=MUTED, alpha=0.6, linewidths=0
    )
    ax.scatter(df.loc[up, "log2fc"], df.loc[up, "neglog"], s=8, color=CASE, alpha=0.8, linewidths=0)
    ax.scatter(
        df.loc[down, "log2fc"], df.loc[down, "neglog"], s=8, color=CONTROL, alpha=0.8, linewidths=0
    )
    for x in (-lfc_threshold, lfc_threshold):
        ax.axvline(x, color=INK2, linestyle=":", linewidth=0.8)
    ax.axhline(-np.log10(alpha), color=INK2, linestyle=":", linewidth=0.8)
    labelled = pd.DataFrame(df.loc[sig]).sort_values("padj").head(n_labels)
    for _, row in labelled.iterrows():
        r = cast(Any, row)
        if r["symbol"]:
            ax.annotate(
                str(r["symbol"]),
                (float(r["log2fc"]), float(r["neglog"])),
                fontsize=6.5,
                color=INK,
                xytext=(3, 2),
                textcoords="offset points",
            )
    ax.set_xlabel("log2 fold change (case vs control)")
    ax.set_ylabel("-log10 adjusted p-value")
    ax.set_title(
        f"Differential expression: {int(cast(Any, up).sum())} higher in case, "
        f"{int(cast(Any, down).sum())} higher in control",
        fontsize=10,
        loc="left",
    )
    _legend(ax, {"higher in case": CASE, "higher in control": CONTROL, "not significant": MUTED})
    return _save(fig, path)


def genes_of_interest(
    log2_normed: pd.DataFrame, arms: pd.Series, rows: list[GeneLookupRow], path: Path
) -> Path | None:
    rows = [r for r in rows if r.gene_id is not None and r.gene_id in log2_normed.columns]
    if not rows:
        return None
    n = len(rows)
    cols = min(4, n)
    nrows = int(np.ceil(n / cols))
    fig, axes = plt.subplots(nrows, cols, figsize=(2.6 * cols, 2.6 * nrows), squeeze=False)
    rng = np.random.default_rng(0)
    for ax, row in zip(axes.flat, rows, strict=False):
        _style(ax)
        for j, arm in enumerate(("control", "case")):
            gsms = [g for g, a in zip(arms.index, arms.to_numpy(), strict=True) if a == arm]
            vals = log2_normed.loc[gsms, row.gene_id].astype(float)
            x = j + rng.uniform(-0.15, 0.15, size=len(vals))
            ax.scatter(
                x, vals, s=22, color=ARM_COLOR[arm], edgecolors=SURFACE, linewidths=1, zorder=3
            )
            ax.hlines(vals.mean(), j - 0.25, j + 0.25, color=INK, linewidth=1.5, zorder=4)
        ax.set_xticks([0, 1])
        ax.set_xticklabels(["control", "case"], fontsize=8)
        ax.set_xlim(-0.6, 1.6)
        label = row.symbol or row.gene_id
        padj = f"padj={row.padj:.1e}" if row.padj is not None else "n/a"
        ax.set_title(f"{label}  {row.verdict}  {padj}", fontsize=8, loc="left")
        ax.set_ylabel("log2 normalized counts", fontsize=7)
    for ax in list(axes.flat)[n:]:
        ax.axis("off")
    fig.tight_layout()
    return _save(fig, path)


def enrichment_bars(summary: EnrichmentSummary, path: Path, n: int = 15) -> Path | None:
    terms = summary.top[:n]
    if not terms:
        return None
    terms = sorted(terms, key=lambda t: t.nes)
    fig, ax = plt.subplots(figsize=(7, max(2.5, 0.32 * len(terms) + 1)))
    _style(ax)
    y = np.arange(len(terms))
    ax.barh(
        y, [t.nes for t in terms], color=[CASE if t.nes > 0 else CONTROL for t in terms], height=0.7
    )
    ax.set_yticks(y)
    ax.set_yticklabels([f"{t.term}  (FDR {t.fdr:.2f})" for t in terms], fontsize=7)
    ax.axvline(0, color=INK2, linewidth=0.8)
    ax.set_xlabel("Normalized enrichment score")
    ax.set_title(f"GSEA, {summary.library}: top terms by FDR", fontsize=10, loc="left")
    _legend(ax, {"up in case": CASE, "up in control": CONTROL})
    return _save(fig, path)

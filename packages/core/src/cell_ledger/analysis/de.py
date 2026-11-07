"""Two-group differential expression with pydeseq2 on the contrast samples only.

Design is ``~arm`` with ``control`` as the reference, or ``~block + arm`` when the
contrast names a blocking variable (donor, patient) and the pairing is complete
enough to model. Unpaired samples are dropped from a blocked fit and reported.
"""

from __future__ import annotations

from typing import Any, cast

import anndata as ad
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field
from pydeseq2.dds import DeseqDataSet
from pydeseq2.ds import DeseqStats

from cell_ledger.analysis.bundle import obs_frame, var_frame
from cell_ledger.report.models import DeResultSummary, DeSummary, GeneRow, Pairing

ARM = "arm"
BLOCK = "block"
DESIGN_SIMPLE = "~arm"
DESIGN_BLOCKED = "~block + arm"
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
    min_per_group: int = Field(default=3, ge=2)


class DesignPlan(BaseModel):
    design: str
    pairing: Pairing
    blocking: str | None
    kept: list[str]
    dropped: list[str] = Field(default_factory=list)
    blocks: dict[str, str] = Field(default_factory=dict)  # gsm -> block level (kept only)
    warnings: list[str] = Field(default_factory=list)


def plan_design(obs: pd.DataFrame, blocking: str | None, *, min_per_group: int) -> DesignPlan:
    """Decide between ``~arm`` and ``~block + arm`` from the pairing actually present."""
    gsms = [str(g) for g in obs.index]
    arms = {g: str(a) for g, a in zip(gsms, obs[ARM], strict=True)}
    if blocking is None:
        return DesignPlan(design=DESIGN_SIMPLE, pairing="none", blocking=None, kept=gsms)
    if blocking not in obs.columns:
        return DesignPlan(
            design=DESIGN_SIMPLE,
            pairing="ignored",
            blocking=blocking,
            kept=gsms,
            warnings=[f"blocking field {blocking!r} is not in the sample sheet; fitting ~arm"],
        )
    levels = {g: str(v) for g, v in zip(gsms, obs[blocking], strict=True)}
    members: dict[str, set[str]] = {}
    for g, lvl in levels.items():
        if lvl and lvl != "nan":
            members.setdefault(lvl, set()).add(arms[g])
    complete = {lvl for lvl, arms_seen in members.items() if arms_seen == {"case", "control"}}
    kept = [g for g in gsms if levels[g] in complete]
    dropped = [g for g in gsms if g not in set(kept)]
    if len(complete) < min_per_group:
        return DesignPlan(
            design=DESIGN_SIMPLE,
            pairing="ignored",
            blocking=blocking,
            kept=gsms,
            warnings=[
                f"only {len(complete)} complete {blocking} pairs (< {min_per_group}); "
                f"pairing ignored, fitting ~arm on all samples"
            ],
        )
    plan = DesignPlan(
        design=DESIGN_BLOCKED,
        pairing="modelled" if not dropped else "incomplete_dropped",
        blocking=blocking,
        kept=kept,
        dropped=dropped,
        blocks={g: levels[g] for g in kept},
    )
    if dropped:
        plan.warnings.append(
            f"{len(dropped)} samples without a {blocking} partner in the other arm were "
            f"dropped from the blocked fit: {dropped}"
        )
    return plan


def run_de(
    adata: ad.AnnData, params: DeParams, *, blocking: str | None = None
) -> tuple[pd.DataFrame, pd.DataFrame, DeResultSummary, DesignPlan]:
    """Returns (results by gene, normalized counts samples x genes, summary, design plan).

    ``adata`` must hold only case and control samples with an ``arm`` column; the
    reference level is forced to ``control`` so a positive log2FC means higher in case.
    """
    obs = obs_frame(adata)
    arms_all = [str(a) for a in obs[ARM]]
    if set(arms_all) != {"case", "control"}:
        raise ValueError(f"DE needs exactly the arms case and control, got {sorted(set(arms_all))}")
    if adata.n_vars == 0:
        raise ValueError("no genes left to test")
    plan = plan_design(obs, blocking, min_per_group=params.min_per_group)
    sub = adata[plan.kept].copy()
    obs = obs_frame(sub)
    arms = [str(a) for a in obs[ARM]]

    counts = pd.DataFrame(
        np.asarray(sub.layers["counts"], dtype=np.int64),
        index=sub.obs_names,
        columns=sub.var_names,
    )
    metadata = pd.DataFrame(
        {ARM: pd.Categorical(arms, categories=["control", "case"])}, index=sub.obs_names
    )
    if plan.design == DESIGN_BLOCKED:
        metadata[BLOCK] = pd.Categorical([plan.blocks[str(g)] for g in sub.obs_names])
    dds = DeseqDataSet(
        counts=counts, metadata=metadata, design=plan.design, quiet=True, n_cpus=params.n_cpus
    )
    dds.deseq2()
    stats = DeseqStats(
        dds, contrast=[ARM, "case", "control"], alpha=params.alpha, quiet=True, n_cpus=params.n_cpus
    )
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
    var = var_frame(sub)
    symbols = var["Symbol"] if "Symbol" in var.columns else pd.Series("", index=sub.var_names)
    results.insert(0, "symbol", symbols.reindex(results.index).fillna("").astype(str).to_numpy())
    results = results.sort_values(["padj", "pvalue"], na_position="last")

    normed = pd.DataFrame(
        np.asarray(dds.layers["normed_counts"]), index=sub.obs_names, columns=sub.var_names
    )

    sig = cast(pd.Series, results["padj"] < params.alpha)
    up = cast(pd.Series, sig & (results["log2fc"] > 0))
    down = cast(pd.Series, sig & (results["log2fc"] < 0))
    summary = DeSummary(
        design=plan.design,
        coefficient=COEFFICIENT,
        blocking=plan.blocking,
        pairing=plan.pairing,
        n_case_used=arms.count("case"),
        n_control_used=arms.count("control"),
        dropped_unpaired=plan.dropped,
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
        plan,
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

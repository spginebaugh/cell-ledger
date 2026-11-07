"""Two-group differential expression with pydeseq2 on the contrast samples only.

Design is ``~arm`` with ``control`` as the reference, or ``~block + arm`` when the
contrast names a blocking variable (donor, patient) and the pairing is complete
enough to model. Unpaired samples are dropped from a blocked fit and reported.

Several samples from the same block in the same arm (four plaques from one patient)
are not independent observations. They are summed into one observation per block
and arm before the fit, the same way DESeq2's ``collapseReplicates`` does, and the
collapse is recorded so the report can say so.
"""

from __future__ import annotations

from dataclasses import dataclass
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
    collapsed: dict[str, list[str]] = Field(
        default_factory=dict, description="observation id -> GSMs summed into it"
    )
    unmodelled_dependence: str | None = Field(
        default=None,
        description="set when samples repeat a donor within an arm but no blocking was declared",
    )
    warnings: list[str] = Field(default_factory=list)

    @property
    def units(self) -> dict[str, list[str]]:
        """Fitted observation -> GSMs, for every kept sample (singletons map to themselves)."""
        out = {g: [g] for g in self.kept}
        for unit, gsms in self.collapsed.items():
            for g in gsms:
                out.pop(g, None)
            out[unit] = list(gsms)
        return out


@dataclass
class DeFit:
    results: pd.DataFrame
    normed: pd.DataFrame  # fitted observations x genes
    summary: DeResultSummary
    plan: DesignPlan
    arms: pd.Series  # arm per fitted observation (normed.index)


def _collapse_plan(
    kept: list[str], blocks: dict[str, str], arms: dict[str, str]
) -> dict[str, list[str]]:
    groups: dict[tuple[str, str], list[str]] = {}
    for g in kept:
        groups.setdefault((blocks[g], arms[g]), []).append(g)
    return {f"{lvl}|{arm}": gsms for (lvl, arm), gsms in groups.items() if len(gsms) > 1}


def plan_design(obs: pd.DataFrame, blocking: str | None, *, min_per_group: int) -> DesignPlan:
    """Decide between ``~arm`` and ``~block + arm`` from the pairing actually present."""
    gsms = [str(g) for g in obs.index]
    arms = {g: str(a) for g, a in zip(gsms, obs[ARM], strict=True)}
    if blocking is None:
        plan = DesignPlan(design=DESIGN_SIMPLE, pairing="none", blocking=None, kept=gsms)
        if "donor" in obs.columns:
            donors = {g: str(v) for g, v in zip(gsms, obs["donor"], strict=True)}
            seen: dict[tuple[str, str], int] = {}
            for g in gsms:
                if donors[g] and donors[g] != "nan":
                    seen[(donors[g], arms[g])] = seen.get((donors[g], arms[g]), 0) + 1
            repeats = sum(n - 1 for n in seen.values())
            if repeats:
                plan.unmodelled_dependence = (
                    f"{repeats} samples repeat a donor within an arm but the contrast declares "
                    "no blocking; they were fitted as independent"
                )
                plan.warnings.append(plan.unmodelled_dependence)
        return plan
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
    blocks = {g: levels[g] for g in kept}
    plan = DesignPlan(
        design=DESIGN_BLOCKED,
        pairing="modelled" if not dropped else "incomplete_dropped",
        blocking=blocking,
        kept=kept,
        dropped=dropped,
        blocks=blocks,
        collapsed=_collapse_plan(kept, blocks, arms),
    )
    if dropped:
        plan.warnings.append(
            f"{len(dropped)} samples without a {blocking} partner in the other arm were "
            f"dropped from the blocked fit: {dropped}"
        )
    if plan.collapsed:
        n = sum(len(v) for v in plan.collapsed.values())
        plan.warnings.append(
            f"{n} samples repeat a {blocking} within an arm and were summed into "
            f"{len(plan.collapsed)} observations before the fit (pseudo-replication)"
        )
    return plan


def run_de(adata: ad.AnnData, params: DeParams, *, blocking: str | None = None) -> DeFit:
    """Fit the contrast. ``adata`` must hold only case and control samples with an
    ``arm`` column; the reference level is forced to ``control`` so a positive log2FC
    means higher in case. Repeated samples per block and arm are summed first."""
    obs = obs_frame(adata)
    arms_all = [str(a) for a in obs[ARM]]
    if set(arms_all) != {"case", "control"}:
        raise ValueError(f"DE needs exactly the arms case and control, got {sorted(set(arms_all))}")
    if adata.n_vars == 0:
        raise ValueError("no genes left to test")
    plan = plan_design(obs, blocking, min_per_group=params.min_per_group)
    sub = adata[plan.kept].copy()
    obs = obs_frame(sub)
    arm_of = {str(g): str(a) for g, a in zip(sub.obs_names, obs[ARM], strict=True)}

    per_sample = pd.DataFrame(
        np.asarray(sub.layers["counts"], dtype=np.int64),
        index=[str(g) for g in sub.obs_names],
        columns=sub.var_names,
    )
    units = plan.units
    unit_ids = [u for u in units if u in per_sample.index] + [
        u for u in units if u not in per_sample.index
    ]
    counts = pd.DataFrame(
        {u: per_sample.loc[units[u]].sum(axis=0) for u in unit_ids}, index=sub.var_names
    ).T.astype(np.int64)
    arms = [arm_of[units[u][0]] for u in unit_ids]
    metadata = pd.DataFrame(
        {ARM: pd.Categorical(arms, categories=["control", "case"])}, index=counts.index
    )
    if plan.design == DESIGN_BLOCKED:
        metadata[BLOCK] = pd.Categorical([plan.blocks[units[u][0]] for u in unit_ids])
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
    results["lfc_se_unshrunk"] = results["lfcSE"]  # meta-analysis needs the unshrunk SE
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
        np.asarray(dds.layers["normed_counts"]), index=counts.index, columns=sub.var_names
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
        gsms_fitted=list(plan.kept),
        collapsed=plan.collapsed,
        n_samples_collapsed=sum(len(v) for v in plan.collapsed.values()),
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
    return DeFit(
        results=results,
        normed=normed,
        summary=DeResultSummary(
            summary=summary,
            top_up=gene_rows(pd.DataFrame(results.loc[up]).head(params.top_n)),
            top_down=gene_rows(pd.DataFrame(results.loc[down]).head(params.top_n)),
        ),
        plan=plan,
        arms=pd.Series(arms, index=counts.index, dtype=str),
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

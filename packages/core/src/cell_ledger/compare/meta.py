"""Cross-dataset statistics on per-dataset summary statistics. No counts, no refitting.

Inputs are genes x datasets frames (NaN where a dataset did not test the gene):
unshrunk log2FC and its SE, the Wald statistic, and padj. Everything is vectorised
over genes.

Pooling is DerSimonian-Laird random effects. Intervals and p-values use the
Hartung-Knapp-Sidik-Jonkman adjustment (t with k-1 degrees of freedom) by default,
which is better calibrated than the normal approximation when few studies contribute.
"""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.stats import t as student_t

from cell_ledger.compare.load import RunData
from cell_ledger.compare.models import CompareParams, GeneMeta, GeneSynthesis, Interval


class EffectMatrices:
    """Aligned genes x datasets frames built from the members' DE tables."""

    def __init__(self, runs: list[RunData]) -> None:
        tables = {r.label: t for r in runs if (t := r.effect_table()) is not None}
        self.labels = list(tables)
        genes = sorted(set().union(*(set(t.index) for t in tables.values())))
        idx = pd.Index(genes, name="gene_id")

        def stack(col: str) -> pd.DataFrame:
            return pd.DataFrame(
                {lab: t[col].reindex(idx) for lab, t in tables.items()}, index=idx, dtype=float
            )

        self.lfc = stack("lfc")
        self.se = stack("se")
        self.stat = stack("stat")
        self.padj = stack("padj")
        symbols = pd.Series("", index=idx, dtype=str)
        for t in tables.values():
            s = t["symbol"].reindex(idx).fillna("")
            symbols = symbols.where(symbols != "", s)
        self.symbol = symbols
        self.n_samples = pd.Series(
            {r.label: float(r.n_fitted) for r in runs if r.label in tables}, dtype=float
        )

    def subset(self, labels: list[str]) -> EffectMatrices:
        other = object.__new__(EffectMatrices)
        other.labels = list(labels)
        for name in ("lfc", "se", "stat", "padj"):
            setattr(other, name, getattr(self, name)[labels])
        other.symbol = self.symbol
        other.n_samples = self.n_samples[labels]
        return other

    @property
    def tested(self) -> pd.DataFrame:
        """Where a dataset contributes an estimate (finite log2FC and positive SE)."""
        return self.lfc.notna() & self.se.notna() & (self.se > 0)


def concordance(stat: pd.DataFrame, min_shared: int = 200) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Pairwise Spearman of Wald statistics over genes tested in both; n shared genes."""
    rho = stat.corr(method="spearman", min_periods=min_shared)
    present = stat.notna().astype(int)
    n_shared = pd.DataFrame(
        present.T.to_numpy() @ present.to_numpy(), index=stat.columns, columns=stat.columns
    )
    return rho, n_shared


def mean_to_others(rho: pd.DataFrame) -> pd.Series:
    off_diagonal = ~np.eye(len(rho), dtype=bool)
    return rho.where(off_diagonal).mean(axis=1, skipna=True)


def benjamini_hochberg(p: np.ndarray) -> np.ndarray:
    """BH adjusted p-values; NaN stays NaN and is not counted."""
    out = np.full(p.shape, np.nan)
    mask = np.isfinite(p)
    m = int(mask.sum())
    if m == 0:
        return out
    pv = p[mask]
    order = np.argsort(pv)
    ranked = pv[order] * m / np.arange(1, m + 1)
    adj = np.minimum.accumulate(ranked[::-1])[::-1]
    res = np.empty(m)
    res[order] = np.minimum(adj, 1.0)
    out[mask] = res
    return out


def random_effects(
    lfc: pd.DataFrame,
    se: pd.DataFrame,
    min_studies: int,
    *,
    interval: Interval = "hksj",
    level: float = 0.95,
) -> pd.DataFrame:
    """DerSimonian-Laird random-effects pooling per gene.

    Returns k (datasets pooled), pooled estimate, its random-effects SE, the SE used for
    the interval (``se_ci``: HKSJ or the same), df, CI, z (= pooled / pooled_se, for
    ranking), p (t with k-1 df under HKSJ, normal otherwise), BH padj, tau2, I2 and Q.
    Genes pooled over fewer than ``min_studies`` datasets get NaN estimates.
    """
    y = lfc.to_numpy(dtype=float)
    s = se.to_numpy(dtype=float)
    valid = np.isfinite(y) & np.isfinite(s) & (s > 0)
    y0 = np.where(valid, y, 0.0)
    s_safe = np.where(valid, s, 1.0)
    w = np.where(valid, 1.0 / s_safe**2, 0.0)
    k = valid.sum(axis=1)
    enough = k >= max(min_studies, 2)

    with np.errstate(invalid="ignore", divide="ignore"):
        sw = w.sum(axis=1)
        fixed = (w * y0).sum(axis=1) / sw
        q = (w * (y0 - fixed[:, None]) ** 2).sum(axis=1)
        df = k - 1
        c = sw - (w**2).sum(axis=1) / sw
        tau2 = np.where(c > 0, np.maximum(0.0, (q - df) / c), 0.0)
        ws = np.where(valid, 1.0 / (s_safe**2 + tau2[:, None]), 0.0)
        sws = ws.sum(axis=1)
        pooled = (ws * y0).sum(axis=1) / sws
        se_pooled = np.sqrt(1.0 / sws)
        z = pooled / se_pooled
        i2 = np.where(q > 0, np.maximum(0.0, (q - df) / q), 0.0)
        weight_share = ws / sws[:, None]
        if interval == "hksj":
            q_hk = (ws * (y0 - pooled[:, None]) ** 2).sum(axis=1) / np.maximum(df, 1)
            se_ci = np.sqrt(q_hk / sws)
            crit = student_t.ppf(0.5 + level / 2, np.maximum(df, 1))
            p = 2.0 * student_t.sf(np.abs(pooled / se_ci), np.maximum(df, 1))
        else:
            se_ci = se_pooled
            crit = np.full(k.shape, norm.ppf(0.5 + level / 2))
            p = 2.0 * norm.sf(np.abs(z))

    for arr in (pooled, se_pooled, se_ci, z, p, tau2, i2, q):
        arr[~enough] = np.nan
    weight_share[~enough] = np.nan
    padj = benjamini_hochberg(p)
    out = pd.DataFrame(
        {
            "k": k,
            "pooled_log2fc": pooled,
            "pooled_se": se_pooled,
            "se_ci": se_ci,
            "df": np.where(enough, df, 0),
            "ci_low": pooled - crit * se_ci,
            "ci_high": pooled + crit * se_ci,
            "z": z,
            "pvalue": p,
            "padj": padj,
            "tau2": tau2,
            "i2": i2,
            "q": q,
        },
        index=lfc.index,
    )
    out.attrs["weight_share"] = pd.DataFrame(weight_share, index=lfc.index, columns=lfc.columns)
    return out


def stouffer(stat: pd.DataFrame, n_samples: pd.Series, min_studies: int) -> pd.Series:
    """Weighted Stouffer combination of per-dataset Wald statistics (weights sqrt(n fitted))."""
    z = stat.to_numpy(dtype=float)
    valid = np.isfinite(z)
    w = np.sqrt(n_samples.reindex(stat.columns).to_numpy(dtype=float))[None, :] * valid
    num = (np.where(valid, z, 0.0) * w).sum(axis=1)
    den = np.sqrt((w**2).sum(axis=1))
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    out[valid.sum(axis=1) < min_studies] = np.nan
    return pd.Series(out, index=stat.index, name="stouffer_z")


def replication(m: EffectMatrices, pooled: pd.Series, alpha: float) -> pd.DataFrame:
    """Per-gene agreement counts, measured against the pooled direction.

    ``n_tested`` counts datasets that contribute an estimate to the pool. A dataset
    whose padj is missing (independent filtering) still contributes its estimate but
    cannot be significant.
    """
    tested = m.tested
    has_padj = tested & m.padj.notna()
    sig = has_padj & (m.padj < alpha)
    pos = tested & (m.lfc > 0)
    neg = tested & (m.lfc < 0)
    pooled_pos = pooled.to_numpy(dtype=float) > 0
    agree = np.where(pooled_pos[:, None], pos.to_numpy(), neg.to_numpy())
    sig_agree = sig.to_numpy() & agree
    n_tested = tested.sum(axis=1).to_numpy()
    n_up = (sig & pos).sum(axis=1).to_numpy()
    n_down = (sig & neg).sum(axis=1).to_numpy()
    n_pos, n_neg = pos.sum(axis=1).to_numpy(), neg.sum(axis=1).to_numpy()
    n_agree = agree.sum(axis=1)
    with np.errstate(invalid="ignore", divide="ignore"):
        rep = np.where(n_tested > 0, sig_agree.sum(axis=1) / n_tested, 0.0)
        cons = np.where(n_tested > 0, n_agree / n_tested, 0.0)
    has_pooled = np.isfinite(pooled.to_numpy(dtype=float))
    majority_disagrees = has_pooled & ((n_pos > n_neg) != pooled_pos) & (n_pos != n_neg)
    return pd.DataFrame(
        {
            "n_tested": n_tested,
            "n_with_padj": has_padj.sum(axis=1).to_numpy(),
            "n_sig": sig.sum(axis=1).to_numpy(),
            "n_up_sig": n_up,
            "n_down_sig": n_down,
            "n_pos": n_pos,
            "n_neg": n_neg,
            "n_agree_pooled": np.where(has_pooled, n_agree, 0),
            "replication": np.where(has_pooled, rep, 0.0),
            "sign_consistency": np.where(has_pooled, cons, 0.0),
            "majority_disagrees_pooled": majority_disagrees,
        },
        index=m.lfc.index,
    )


def gene_table(m: EffectMatrices, params: CompareParams, *, min_studies: int) -> pd.DataFrame:
    """One row per gene in the union: pooled effect, agreement with it, robustness."""
    re = random_effects(m.lfc, m.se, min_studies, interval=params.interval)
    rep = replication(m, cast(pd.Series, re["pooled_log2fc"]), params.alpha)
    table = pd.concat([rep, re], axis=1)
    table["stouffer_z"] = stouffer(m.stat, m.n_samples, min_studies)
    table.insert(0, "symbol", m.symbol.reindex(table.index).fillna(""))
    table["robust"] = (
        (table["padj"] < params.alpha)
        & (table["sign_consistency"] >= params.sign_consistency)
        & (table["replication"] >= params.min_replication)
        & (table["n_tested"] >= min_studies)
    ).fillna(False)
    table.attrs["weight_share"] = re.attrs["weight_share"]
    return table


def pooled_z(table: pd.DataFrame) -> pd.DataFrame:
    """A results-like frame (symbol, stat) for GSEA preranked on the pooled statistic."""
    out = pd.DataFrame({"symbol": table["symbol"], "stat": table["z"]}, index=table.index)
    return out.loc[out["stat"].notna() & (out["symbol"] != "")]


def _opt(v: object) -> float | None:
    f = float(cast(float, v))
    return None if np.isnan(f) else f


def gene_meta(gene_id: str, row: pd.Series) -> GeneMeta:
    r = cast(dict[str, object], row.to_dict())
    return GeneMeta(
        gene_id=gene_id,
        symbol=(str(r["symbol"]) or None),
        n_tested=int(cast(int, r["n_tested"])),
        n_with_padj=int(cast(int, r["n_with_padj"])),
        n_sig=int(cast(int, r["n_sig"])),
        n_up_sig=int(cast(int, r["n_up_sig"])),
        n_down_sig=int(cast(int, r["n_down_sig"])),
        n_pos=int(cast(int, r["n_pos"])),
        n_neg=int(cast(int, r["n_neg"])),
        n_agree_pooled=int(cast(int, r["n_agree_pooled"])),
        replication=float(cast(float, r["replication"])),
        sign_consistency=float(cast(float, r["sign_consistency"])),
        majority_disagrees_pooled=bool(r["majority_disagrees_pooled"]),
        pooled_log2fc=_opt(r["pooled_log2fc"]),
        pooled_se=_opt(r["pooled_se"]),
        se_ci=_opt(r["se_ci"]),
        df=int(cast(int, r["df"])) if _opt(r["pooled_log2fc"]) is not None else None,
        ci_low=_opt(r["ci_low"]),
        ci_high=_opt(r["ci_high"]),
        z=_opt(r["z"]),
        pvalue=_opt(r["pvalue"]),
        padj=_opt(r["padj"]),
        tau2=_opt(r["tau2"]),
        i2=_opt(r["i2"]),
        stouffer_z=_opt(r["stouffer_z"]),
        robust=bool(r["robust"]),
    )


def synthesize(
    table: pd.DataFrame, labels: list[str], params: CompareParams, *, min_studies: int
) -> GeneSynthesis:
    """Counts plus top tables. Top tables rank robust genes with |pooled log2FC| >=
    ``params.lfc_threshold`` by pooled z, so tiny but very precise effects do not crowd
    out the biology; the counts are reported with and without that floor."""
    pooled = table["pooled_log2fc"].notna()
    sig = pooled & (table["padj"] < params.alpha)
    robust = table["robust"].astype(bool)
    lfc = table["pooled_log2fc"]
    up = table.loc[robust & (lfc > 0)]
    down = table.loc[robust & (lfc < 0)]
    thr = params.lfc_threshold
    up_lfc = up.loc[up["pooled_log2fc"] >= thr].sort_values("z", ascending=False)
    down_lfc = down.loc[down["pooled_log2fc"] <= -thr].sort_values("z", ascending=True)
    return GeneSynthesis(
        members=labels,
        min_studies=min_studies,
        alpha=params.alpha,
        sign_consistency=params.sign_consistency,
        min_replication=params.min_replication,
        interval=params.interval,
        n_genes_union=len(table),
        n_genes_pooled=int(cast(Any, pooled).sum()),
        n_sig_pooled=int(cast(Any, sig).sum()),
        n_robust=int(cast(Any, robust).sum()),
        n_robust_up=len(up),
        n_robust_down=len(down),
        lfc_threshold=thr,
        n_robust_up_lfc=len(up_lfc),
        n_robust_down_lfc=len(down_lfc),
        top_up=[gene_meta(str(g), r) for g, r in up_lfc.head(params.top_n).iterrows()],
        top_down=[gene_meta(str(g), r) for g, r in down_lfc.head(params.top_n).iterrows()],
    )

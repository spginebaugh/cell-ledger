"""Deterministic per-sample and per-dataset QC on raw counts.

Everything here is computed from the counts and the sample sheet. Flags are
advisory: the pipeline records them and the report shows them, nothing is
silently dropped.
"""

from __future__ import annotations

from typing import Any

import anndata as ad
import numpy as np

from cell_ledger.analysis.annotation import mito_mask, ribo_mask, symbol_to_gene_id
from cell_ledger.analysis.bundle import obs_frame, var_frame
from cell_ledger.report.models import PcaSummary, QcResult, SampleQc

FEMALE_MARKER = "XIST"
MALE_MARKER = "RPS4Y1"
MALE_MIN_Y_CPM = 2.0  # RPS4Y1 clearly expressed: male
FEMALE_MAX_Y_CPM = 1.0  # RPS4Y1 absent ...
FEMALE_MIN_XIST_CPM = 5.0  # ... and XIST expressed: female; anything else is left unpredicted
SEX_ALIASES = {"f": "female", "female": "female", "m": "male", "male": "male"}


def log_cpm(counts: np.ndarray) -> np.ndarray:
    lib = counts.sum(axis=1, keepdims=True).astype(float)
    lib[lib == 0] = 1.0
    return np.log2(counts / lib * 1e6 + 1.0)


def _expressed_mask(counts: np.ndarray, min_count: int = 10, min_samples: int = 2) -> np.ndarray:
    mask = (counts >= min_count).sum(axis=0) >= min(min_samples, counts.shape[0])
    if mask.sum() < 50:
        mask = counts.sum(axis=0) > 0
    return mask


def _pca(logcpm: np.ndarray, n_top: int) -> tuple[np.ndarray, list[float], int]:
    var = logcpm.var(axis=0)
    top = np.argsort(var)[::-1][: min(n_top, logcpm.shape[1])]
    x = logcpm[:, top]
    x = x - x.mean(axis=0, keepdims=True)
    _, s, vt = np.linalg.svd(x, full_matrices=False)
    coords = x @ vt[:2].T
    total = float((s**2).sum()) or 1.0
    ratio = [float(v) for v in (s[:2] ** 2) / total]
    while len(ratio) < 2:
        ratio.append(0.0)
    if coords.shape[1] < 2:
        coords = np.hstack([coords, np.zeros((coords.shape[0], 2 - coords.shape[1]))])
    return coords, ratio, len(top)


def _r2_by_group(values: np.ndarray, groups: list[str]) -> float | None:
    g = np.asarray(groups)
    if len(set(groups)) < 2 or len(values) < 3:
        return None
    grand = values.mean()
    ss_tot = float(((values - grand) ** 2).sum())
    if ss_tot == 0:
        return None
    ss_between = sum(
        (g == lvl).sum() * (values[g == lvl].mean() - grand) ** 2 for lvl in set(groups)
    )
    return float(ss_between / ss_tot)


def _predict_sex(xist_cpm: float, y_cpm: float) -> str | None:
    """Y-chromosome expression decides; XIST alone is only trusted when Y is absent."""
    if y_cpm >= MALE_MIN_Y_CPM:
        return "male"
    if y_cpm < FEMALE_MAX_Y_CPM and xist_cpm >= FEMALE_MIN_XIST_CPM:
        return "female"
    return None


def _normalize_sex(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    return SEX_ALIASES.get(value.strip().lower())


def run_qc(
    adata: ad.AnnData,
    *,
    min_library_size: float = 1e5,
    low_library_size: float = 1e6,
    min_within_arm_corr: float = 0.8,
    max_pct_mito: float = 20.0,
    n_top_genes: int = 2000,
    sex_check: bool = True,
) -> QcResult:
    params: dict[str, Any] = {
        "min_library_size": min_library_size,
        "low_library_size": low_library_size,
        "min_within_arm_corr": min_within_arm_corr,
        "max_pct_mito": max_pct_mito,
        "n_top_genes": n_top_genes,
        "sex_check": sex_check,
    }
    counts = np.asarray(adata.layers["counts"], dtype=np.int64)
    obs, var = obs_frame(adata), var_frame(adata)
    gsms = list(adata.obs_names)
    arms = [str(a) for a in obs["arm"]] if "arm" in obs.columns else ["all"] * adata.n_obs
    lib = counts.sum(axis=1)
    safe_lib = np.where(lib == 0, 1, lib).astype(float)
    detected = (counts > 0).sum(axis=1)
    mito = mito_mask(var).to_numpy()
    ribo = ribo_mask(var).to_numpy()
    pct_mito = counts[:, mito].sum(axis=1) / safe_lib * 100
    pct_ribo = counts[:, ribo].sum(axis=1) / safe_lib * 100

    expressed = _expressed_mask(counts)
    logcpm_all = log_cpm(counts)
    logcpm = logcpm_all[:, expressed]

    pca = None
    corr = None
    if adata.n_obs >= 3 and logcpm.shape[1] >= 2:
        coords, ratio, n_used = _pca(logcpm, n_top_genes)
        pca = PcaSummary(
            n_genes_used=n_used,
            variance_ratio=ratio,
            coords={g: [float(c[0]), float(c[1])] for g, c in zip(gsms, coords, strict=True)},
            arm_r2_pc1=_r2_by_group(coords[:, 0], arms),
        )
        gene_var = logcpm.var(axis=0)
        top = np.argsort(gene_var)[::-1][: min(n_top_genes, logcpm.shape[1])]
        with np.errstate(invalid="ignore"):
            corr = np.corrcoef(logcpm[:, top])

    symbol_ids = symbol_to_gene_id(var)
    sex_idx: tuple[int, int] | None = None
    if sex_check and FEMALE_MARKER in symbol_ids and MALE_MARKER in symbol_ids:
        names = list(adata.var_names)
        try:
            sex_idx = (names.index(symbol_ids[FEMALE_MARKER]), names.index(symbol_ids[MALE_MARKER]))
        except ValueError:
            sex_idx = None

    samples: list[SampleQc] = []
    arm_arr = np.asarray(arms)
    for i, gsm in enumerate(gsms):
        flags: list[str] = []
        if lib[i] < min_library_size:
            flags.append("very_low_library_size")
        elif lib[i] < low_library_size:
            flags.append("low_library_size")
        if pct_mito[i] > max_pct_mito:
            flags.append("high_mito_fraction")

        same = other = None
        if corr is not None and len(set(arms)) >= 1:
            same_mask = (arm_arr == arms[i]) & (np.arange(len(gsms)) != i)
            other_mask = arm_arr != arms[i]
            same = float(np.nanmean(corr[i, same_mask])) if same_mask.any() else None
            other = float(np.nanmean(corr[i, other_mask])) if other_mask.any() else None
            if same is not None and same < min_within_arm_corr:
                flags.append("low_within_arm_correlation")
            if same is not None and other is not None and other > same:
                flags.append("closer_to_other_arm")

        reported = _normalize_sex(obs["sex"].iloc[i]) if "sex" in obs.columns else None
        predicted = None
        if sex_idx is not None:
            xist_cpm = counts[i, sex_idx[0]] / safe_lib[i] * 1e6
            y_cpm = counts[i, sex_idx[1]] / safe_lib[i] * 1e6
            predicted = _predict_sex(xist_cpm, y_cpm)
            if reported and predicted and reported != predicted:
                flags.append("sex_mismatch")

        samples.append(
            SampleQc(
                gsm=gsm,
                arm=arms[i],
                library_size=int(lib[i]),
                detected_genes=int(detected[i]),
                pct_mito=float(pct_mito[i]),
                pct_ribo=float(pct_ribo[i]),
                mean_corr_same_arm=same,
                mean_corr_other_arm=other,
                reported_sex=reported,
                predicted_sex=predicted,
                flags=flags,
            )
        )

    dataset_flags: list[str] = []
    median_lib = float(np.median(lib)) if len(lib) else 0.0
    if median_lib < low_library_size:
        dataset_flags.append("low_median_library_size")
    n_swapped = sum("closer_to_other_arm" in s.flags for s in samples)
    arms_separated = pca is not None and pca.arm_r2_pc1 is not None and pca.arm_r2_pc1 >= 0.5
    if n_swapped >= max(2, round(0.25 * len(samples))) and not arms_separated:
        dataset_flags.append("possible_group_swap")
    if any("sex_mismatch" in s.flags for s in samples):
        dataset_flags.append("sex_mismatches")
    if pca is not None and pca.arm_r2_pc1 is not None and pca.arm_r2_pc1 < 0.1:
        dataset_flags.append("arms_not_separated_on_pc1")

    return QcResult(
        samples=samples, median_library_size=median_lib, pca=pca, flags=dataset_flags, params=params
    )

"""Gene-centric answers: per-gene verdicts for a contrast, and marker-panel scoring."""

from __future__ import annotations

from typing import Any, cast

import numpy as np
import pandas as pd

from cell_ledger.analysis.annotation import symbol_to_gene_id
from cell_ledger.report.models import (
    GeneLookupRow,
    MarkerExpectation,
    MarkerResult,
    MarkerScore,
)


def _resolve(query: str, var: pd.DataFrame, symbols: dict[str, str]) -> str | None:
    q = query.strip()
    if q in var.index:
        return q
    return symbols.get(q.upper())


def gene_ids(queries: list[str], var: pd.DataFrame) -> list[str]:
    """GeneIDs for the symbols or ids in ``queries`` that the annotation knows, resolved the
    same way :func:`lookup_genes` resolves them."""
    if not queries:
        return []
    symbols = symbol_to_gene_id(var)
    return [g for q in queries if (g := _resolve(q, var, symbols)) is not None]


def lookup_genes(
    queries: list[str],
    var: pd.DataFrame,
    *,
    results: pd.DataFrame | None,
    normed: pd.DataFrame | None,
    arms: pd.Series | None,
    alpha: float = 0.05,
) -> list[GeneLookupRow]:
    """One row per query. ``var`` is the unfiltered annotation, so filtered genes read as
    ``not_tested`` rather than ``not_found``."""
    symbols = symbol_to_gene_id(var)
    ranks: dict[str, int] = {}
    if results is not None:
        ordered = results.sort_values(["padj", "pvalue"], na_position="last").index
        ranks = {str(g): i + 1 for i, g in enumerate(ordered)}
    rows: list[GeneLookupRow] = []
    for q in queries:
        gid = _resolve(q, var, symbols)
        symbol = None
        if gid is not None and "Symbol" in var.columns:
            s = var.loc[gid, "Symbol"]
            symbol = str(s) if isinstance(s, str) and s else None
        if gid is None:
            rows.append(
                GeneLookupRow(
                    query=q,
                    gene_id=None,
                    symbol=None,
                    verdict="not_found",
                    reason="symbol_not_in_annotation",
                )
            )
            continue
        if results is None:
            rows.append(
                GeneLookupRow(
                    query=q, gene_id=gid, symbol=symbol, verdict="not_run", reason="de_not_run"
                )
            )
            continue
        if gid not in results.index:
            rows.append(
                GeneLookupRow(
                    query=q,
                    gene_id=gid,
                    symbol=symbol,
                    verdict="not_tested",
                    reason="filtered_before_testing",
                )
            )
            continue
        r = cast(Any, results.loc[gid])
        padj = None if pd.isna(r["padj"]) else float(r["padj"])
        pvalue_missing = bool(pd.isna(r["pvalue"]))
        lfc = float(r["log2fc"])
        reason = None
        if pvalue_missing:
            verdict, reason = "untestable", "outlier_or_all_zero"
        elif padj is None:
            verdict, reason = "untestable", "independent_filtering"
        elif padj < alpha and lfc > 0:
            verdict = "up"
        elif padj < alpha and lfc < 0:
            verdict = "down"
        else:
            verdict = "no_evidence"
        mean_case = mean_ctrl = None
        if normed is not None and arms is not None and gid in normed.columns:
            col = normed[gid].astype(float).reindex(arms.index).to_numpy()
            arm_values = arms.to_numpy()
            mean_case = float(col[arm_values == "case"].mean())
            mean_ctrl = float(col[arm_values == "control"].mean())
        rows.append(
            GeneLookupRow(
                query=q,
                gene_id=gid,
                symbol=symbol,
                verdict=verdict,
                reason=reason,
                log2fc=lfc,
                padj=padj,
                base_mean=float(r["base_mean"]),
                mean_norm_case=mean_case,
                mean_norm_control=mean_ctrl,
                rank_by_padj=ranks.get(gid),
            )
        )
    return rows


def score_markers(
    expectations: list[MarkerExpectation], lookups: list[GeneLookupRow], *, top_n: int = 200
) -> MarkerScore:
    """Fraction of expected markers that are significant with the right sign, and that
    sit in the top ``top_n`` genes by adjusted p-value with the right sign (eval 4)."""
    by_query = {row.query.upper(): row for row in lookups}
    results: list[MarkerResult] = []
    for exp in expectations:
        row = by_query.get(exp.symbol.upper()) or GeneLookupRow(
            query=exp.symbol, gene_id=None, symbol=None, verdict="not_found"
        )
        sign_ok = row.log2fc is not None and (
            (exp.direction == "up" and row.log2fc > 0)
            or (exp.direction == "down" and row.log2fc < 0)
        )
        recovered = row.verdict == exp.direction
        in_top = bool(sign_ok and row.rank_by_padj is not None and row.rank_by_padj <= top_n)
        results.append(
            MarkerResult(
                expected=exp, lookup=row, recovered_sig=recovered, in_top_n_correct_sign=in_top
            )
        )
    n = len(expectations)
    n_rec = sum(r.recovered_sig for r in results)
    n_top = sum(r.in_top_n_correct_sign for r in results)
    return MarkerScore(
        n_expected=n,
        n_recovered_sig=n_rec,
        n_in_top_n=n_top,
        top_n=top_n,
        fraction_recovered=float(n_rec / n) if n else float("nan"),
        fraction_in_top_n=float(n_top / n) if n else float("nan"),
        results=results,
    )


def log2_normalized(normed: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        np.log2(normed.to_numpy(dtype=float) + 1.0), index=normed.index, columns=normed.columns
    )

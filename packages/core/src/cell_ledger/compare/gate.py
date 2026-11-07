"""Membership: which runs enter the ledger, which are pooled by default, and why.

Hard exclusions need evidence of an input or design problem, never of a disagreeing
result: the run must have a DE result, qualified runs are kept or dropped per
params, and two runs sharing fitted GSMs are one piece of evidence (the smaller goes).

Concordance of Wald statistics is a diagnostic. A run with a stratum is judged against
the other runs of that stratum; a run without one is judged against every run. A run
whose mean Spearman correlation with its reference runs is strongly negative is
flagged ``labels_reversed``: it is left out of the default pool, a question is
written for the user, and the synthesis is also reported with it included. A run with
low but not negative agreement is flagged ``low_concordance`` and still pooled, with
the synthesis also reported without it. Nothing is removed for disagreeing.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import numpy as np

from cell_ledger.compare.load import RunData
from cell_ledger.compare.meta import EffectMatrices, concordance
from cell_ledger.compare.models import CompareParams, Concordance, Exclusion, MemberFlag

MIN_GROUP_FOR_CONCORDANCE = 3


@dataclass
class GateResult:
    included: list[RunData]
    excluded: list[Exclusion] = field(default_factory=list)
    flags: dict[str, list[MemberFlag]] = field(default_factory=dict)
    pooled: set[str] = field(default_factory=set)
    groups: dict[str, str] = field(default_factory=dict)
    concordance: Concordance | None = None
    questions: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _exclude(run: RunData, reason: str, detail: str) -> Exclusion:
    return Exclusion(
        label=run.label,
        gse=run.report.gse,
        contrast=run.report.contrast.name,
        run_dir=str(run.run_dir),
        reason=reason,  # type: ignore[arg-type]
        detail=detail,
    )


def _opt(v: object) -> float | None:
    f = float(cast(Any, v))
    return None if np.isnan(f) else f


def hard_gate(runs: list[RunData], params: CompareParams) -> tuple[list[RunData], list[Exclusion]]:
    kept: list[RunData] = []
    excluded: list[Exclusion] = []
    for r in runs:
        if r.report.status != "complete":
            excluded.append(
                _exclude(
                    r,
                    "not_complete",
                    f"status {r.report.status}: {'; '.join(r.report.blockers) or 'no DE'}",
                )
            )
        elif r.effect_table() is None:
            excluded.append(_exclude(r, "no_de_table", "report is complete but has no DE table"))
        elif r.report.qualifications and not params.include_qualified:
            excluded.append(_exclude(r, "qualified", "; ".join(r.report.qualifications)))
        else:
            kept.append(r)

    # Independence: two runs sharing fitted GSMs are one piece of evidence. Keep the larger.
    kept.sort(key=lambda r: -r.n_fitted)
    independent: list[RunData] = []
    for r in kept:
        clash = next((k for k in independent if k.gsms_fitted & r.gsms_fitted), None)
        if clash is None:
            independent.append(r)
        else:
            shared = sorted(clash.gsms_fitted & r.gsms_fitted)
            excluded.append(
                _exclude(
                    r,
                    "shares_samples",
                    f"shares {len(shared)} fitted GSMs with {clash.label} (e.g. {shared[:3]})",
                )
            )
    return independent, excluded


def gate(
    runs: list[RunData], params: CompareParams, strata: dict[str, str] | None = None
) -> GateResult:
    strata = strata or {}
    kept, excluded = hard_gate(runs, params)
    out = GateResult(included=kept, excluded=excluded)
    if not kept:
        return out
    for r in kept:
        if r.unshrunk_se_source == "reconstructed":
            out.warnings.append(
                f"{r.label}: de_results lacks lfc_se_unshrunk (run predates it); the unshrunk SE "
                "was reconstructed from the unshrunk log2FC and the Wald statistic"
            )
    out.groups = {r.label: strata.get(r.label) or strata.get(r.report.gse) or "all" for r in kept}
    out.flags = {r.label: [] for r in kept}
    out.pooled = {r.label for r in kept}

    m = EffectMatrices(kept)
    rho, n_shared = concordance(m.stat)
    means: dict[str, float | None] = dict.fromkeys(m.labels)

    def reference(lab: str, exclude: set[str]) -> list[str]:
        """Runs ``lab`` is judged against: its stratum, or every run when it has none."""
        group = out.groups[lab]
        pool = m.labels if group == "all" else [x for x in m.labels if out.groups[x] == group]
        return [x for x in pool if x != lab and x not in exclude]

    def mean_against(lab: str, ref: list[str]) -> float | None:
        if not ref:
            return None
        row = rho.loc[lab, ref]
        return None if row.isna().all() else _opt(row.mean(skipna=True))

    unassessed: set[str] = set()
    for lab in m.labels:
        ref = reference(lab, set())
        if len(ref) < MIN_GROUP_FOR_CONCORDANCE - 1:
            unassessed.add(lab)
            out.flags[lab].append("concordance_unassessed")
            out.warnings.append(
                f"{lab}: only {len(ref)} other run(s) to judge against (stratum "
                f"{out.groups[lab]!r}); at least {MIN_GROUP_FOR_CONCORDANCE - 1} are needed, "
                "so its concordance was not assessed"
            )
        elif mean_against(lab, ref) is None:
            unassessed.add(lab)
            out.flags[lab].append("concordance_unassessed")
            out.warnings.append(f"{lab}: too few shared genes to assess concordance")

    # Pass 1: genome-wide reversal against the reference set.
    reversed_: set[str] = set()
    for lab in m.labels:
        if lab in unassessed:
            continue
        v = mean_against(lab, reference(lab, set()))
        if v is not None and v < params.reversed_concordance:
            reversed_.add(lab)
            means[lab] = v
            out.flags[lab].append("labels_reversed")
            others = len(reference(lab, set()))
            if not params.pool_flagged:
                out.pooled.discard(lab)
            out.questions.append(
                f"{lab}: its Wald statistics correlate at {v:+.2f} (Spearman, mean over the "
                f"{others} other runs of {out.groups[lab]!r}), a genome-wide reversal. The case "
                "and control labels look swapped relative to the other datasets, which the "
                "pipeline cannot verify from the record. Confirm which arm is the case before "
                "trusting it; it is "
                + (
                    "pooled anyway (pool_flagged)."
                    if params.pool_flagged
                    else "left out of the default pool and reported as a sensitivity result."
                )
            )
    # Pass 2: low agreement, judged without the reversed runs so they cannot drag others down.
    for lab in m.labels:
        if lab in unassessed or lab in reversed_:
            continue
        ref = reference(lab, reversed_)
        v = mean_against(lab, ref)
        means[lab] = v
        if v is not None and v < params.low_concordance:
            out.flags[lab].append("low_concordance")
            out.warnings.append(
                f"{lab}: mean Spearman of Wald statistics with the {len(ref)} other runs of "
                f"{out.groups[lab]!r} is {v:+.2f} (< {params.low_concordance}); it is pooled, and "
                "the synthesis without it is reported as a sensitivity result"
            )

    out.concordance = Concordance(
        members=list(m.labels),
        spearman=[[_opt(v) for v in row] for row in rho.to_numpy()],
        n_shared=[[int(v) for v in row] for row in n_shared.to_numpy()],
        mean_to_others=means,
        groups=dict(out.groups),
    )
    return out

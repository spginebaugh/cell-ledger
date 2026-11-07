"""Cross-dataset comparison over finished run directories.

``run_comparison`` reads each run's ``report.json`` and tables, gates membership,
pools per-gene effects (random effects on unshrunk log2FC), summarises pathways and
writes ``comparison.json`` (canonical), ``comparison.md``, ``questions.md`` and TSV
tables into an output directory. Like the per-dataset pipeline, the write is atomic
and any error is recorded in the report rather than raised. A member that cannot be
read is recorded as excluded and the rest are compared.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import traceback
from collections.abc import Sequence
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

from cell_ledger.analysis.enrichment import EnrichmentParams, run_prerank
from cell_ledger.compare import figures
from cell_ledger.compare.gate import GateResult, gate
from cell_ledger.compare.load import RunData, load_run
from cell_ledger.compare.meta import (
    EffectMatrices,
    gene_meta,
    gene_table,
    pooled_z,
    synthesize,
)
from cell_ledger.compare.models import (
    SLUG,
    AcrossVerdict,
    CompareParams,
    ComparisonReport,
    Exclusion,
    GeneLeaveOneOut,
    GeneLookupAcross,
    GeneMeta,
    LeaveOneOut,
    MarkerAcross,
    MarkerAcrossScore,
    Member,
    QuerySet,
    Sensitivity,
)
from cell_ledger.compare.pathways import synthesize_pathways
from cell_ledger.compare.render import render_markdown
from cell_ledger.report.models import MarkerExpectation

COMPARISON_JSON = "comparison.json"
_SLUG_RE = re.compile(SLUG)


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for pkg in ("cell-ledger", "pandas", "numpy", "scipy", "gseapy"):
        try:
            out[pkg] = version(pkg)
        except Exception:
            out[pkg] = "unknown"
    return out


def _check_output_dir(final: Path) -> None:
    if final.exists() and any(final.iterdir()) and not (final / COMPARISON_JSON).exists():
        raise ValueError(
            f"{final} exists, is not empty and holds no {COMPARISON_JSON}; refusing to overwrite"
        )


def _inside(out: Path, path: Path) -> Path:
    """``path`` resolved, guaranteed to be inside ``out``."""
    resolved = path.resolve()
    root = out.resolve()
    if root != resolved and root not in resolved.parents:
        raise ValueError(f"refusing to write outside the output directory: {path}")
    return resolved


def _member(r: RunData, g: GateResult, stratum: str | None) -> Member:
    rep = r.report
    rec = rep.reconciliation
    de = rep.de.summary if rep.de else None
    return Member(
        label=r.label,
        gse=rep.gse,
        contrast=rep.contrast.name,
        run_dir=str(r.run_dir),
        stratum=stratum,
        concordance_group=g.groups.get(r.label, "all"),
        tier="qualified" if rep.qualifications else "clean",
        pooled=r.label in g.pooled,
        flags=list(g.flags.get(r.label, [])),
        case_label=rep.contrast.case_label,
        control_label=rep.contrast.control_label,
        n_case=de.n_case_used if de else (rec.n_case if rec else 0),
        n_control=de.n_control_used if de else (rec.n_control if rec else 0),
        n_samples_fitted=len(r.gsms_fitted),
        design=de.design if de else "",
        pairing=de.pairing if de else "none",
        collapsed_samples=de.n_samples_collapsed if de else 0,
        median_library_size=rep.qc.median_library_size if rep.qc else 0.0,
        n_genes_tested=de.n_genes_tested if de else 0,
        n_sig=de.n_sig if de else 0,
        qc_flags=rep.qc.flags if rep.qc else [],
        qualifications=rep.qualifications,
        context=rep.context,
        mean_concordance=(g.concordance.mean_to_others.get(r.label) if g.concordance else None),
        unshrunk_se_source=r.unshrunk_se_source,
        fingerprint=rep.fingerprint,
        created_at=rep.created_at,
    )


def _resolve(query: str, table: pd.DataFrame) -> str | None:
    q = query.strip()
    if q in table.index:
        return q
    hits = table.index[table["symbol"].str.upper() == q.upper()]
    return str(hits[0]) if len(hits) else None


def _per_member(gene_id: str, m: EffectMatrices, alpha: float) -> dict[str, str]:
    out: dict[str, str] = {}
    for lab in m.labels:
        lfc, padj = m.lfc.at[gene_id, lab], m.padj.at[gene_id, lab]
        if np.isnan(lfc):
            out[lab] = "not_tested"
        elif np.isnan(padj):
            out[lab] = "untestable"
        elif padj < alpha:
            out[lab] = "up" if lfc > 0 else "down"
        else:
            out[lab] = "no_evidence"
    return out


def verdict_for(
    meta: GeneMeta, params: CompareParams, min_studies: int
) -> tuple[AcrossVerdict, str]:
    """Across-dataset verdict from a gene's pooled row; agreement is against the pooled sign."""
    if meta.n_tested < min_studies:
        return "insufficient", f"tested in {meta.n_tested} datasets, need {min_studies}"
    if meta.pooled_log2fc is None or meta.padj is None:
        return "insufficient", "no pooled estimate"
    direction = "up" if meta.pooled_log2fc > 0 else "down"
    n_dir = meta.n_up_sig if direction == "up" else meta.n_down_sig
    if meta.robust:
        return (
            cast(AcrossVerdict, f"replicated_{direction}"),
            f"significant {direction} in {n_dir}/{meta.n_tested}, pooled padj {meta.padj:.2e}",
        )
    if meta.n_up_sig and meta.n_down_sig:
        return (
            "inconsistent",
            f"significant up in {meta.n_up_sig} and down in {meta.n_down_sig} of "
            f"{meta.n_tested} datasets",
        )
    if meta.padj < params.alpha and meta.sign_consistency >= params.sign_consistency:
        return (
            cast(AcrossVerdict, f"pooled_{direction}"),
            f"pooled padj {meta.padj:.2e}, sign {direction} in {meta.n_agree_pooled}/"
            f"{meta.n_tested} datasets, but significant {direction} in only "
            f"{n_dir}/{meta.n_tested}",
        )
    if meta.padj < params.alpha:
        return (
            "inconsistent",
            f"pooled padj {meta.padj:.2e} but only {meta.n_agree_pooled}/{meta.n_tested} datasets "
            f"point {direction}"
            + (" (the majority points the other way)" if meta.majority_disagrees_pooled else ""),
        )
    return (
        "no_evidence",
        f"pooled padj {meta.padj:.2e}, significant in {meta.n_sig}/{meta.n_tested}",
    )


def lookup_across(
    queries: list[str],
    table: pd.DataFrame,
    m: EffectMatrices,
    params: CompareParams,
    min_studies: int,
) -> list[GeneLookupAcross]:
    rows: list[GeneLookupAcross] = []
    loo_tables: dict[str, pd.DataFrame] = {}
    for q in queries:
        gid = _resolve(q, table)
        if gid is None:
            rows.append(
                GeneLookupAcross(
                    query=q,
                    gene_id=None,
                    symbol=None,
                    verdict="not_found",
                    detail="not tested in any dataset (unknown symbol or filtered everywhere)",
                )
            )
            continue
        meta = gene_meta(gid, table.loc[gid])
        verdict, detail = verdict_for(meta, params, min_studies)
        loo: list[GeneLeaveOneOut] = []
        if len(m.labels) >= 3:
            for lab in m.labels:
                if lab not in loo_tables:
                    rest = [x for x in m.labels if x != lab]
                    loo_tables[lab] = gene_table(
                        m.subset(rest), params, min_studies=min(min_studies, len(rest))
                    )
                t = loo_tables[lab]
                meta_wo = gene_meta(gid, t.loc[gid])
                v_wo, _ = verdict_for(meta_wo, params, min(min_studies, len(m.labels) - 1))
                loo.append(
                    GeneLeaveOneOut(
                        member=lab,
                        pooled_log2fc=meta_wo.pooled_log2fc,
                        ci_low=meta_wo.ci_low,
                        ci_high=meta_wo.ci_high,
                        pvalue=meta_wo.pvalue,
                        verdict=v_wo,
                        changed=v_wo != verdict,
                    )
                )
        rows.append(
            GeneLookupAcross(
                query=q,
                gene_id=gid,
                symbol=meta.symbol,
                verdict=verdict,
                detail=detail,
                meta=meta,
                per_member=_per_member(gid, m, params.alpha),
                leave_one_out=loo,
                driven_by=[x.member for x in loo if x.changed],
            )
        )
    return rows


def score_markers_across(
    expectations: list[MarkerExpectation], lookups: list[GeneLookupAcross]
) -> MarkerAcrossScore:
    by = {r.query.upper(): r for r in lookups}
    results = []
    for e in expectations:
        row = by.get(e.symbol.upper()) or GeneLookupAcross(
            query=e.symbol, gene_id=None, symbol=None, verdict="not_found", detail="not looked up"
        )
        results.append(
            MarkerAcross(
                expected=e, lookup=row, recovered=row.verdict == f"replicated_{e.direction}"
            )
        )
    n = len(expectations)
    rec = sum(r.recovered for r in results)
    return MarkerAcrossScore(
        n_expected=n,
        n_recovered=rec,
        fraction_recovered=rec / n if n else float("nan"),
        results=results,
    )


def _robust_set(t: pd.DataFrame) -> set[str]:
    return set(t.index[t["robust"].to_numpy(dtype=bool)])


def _spearman_z(a: pd.DataFrame, b: pd.DataFrame) -> float | None:
    za = a["z"].to_numpy(dtype=float)
    zb = b["z"].reindex(a.index).to_numpy(dtype=float)
    both = np.isfinite(za) & np.isfinite(zb)
    if int(both.sum()) < 10:
        return None
    return float(cast(Any, spearmanr(za[both], zb[both])).correlation)


def leave_one_out(
    m: EffectMatrices, full: pd.DataFrame, params: CompareParams, min_studies: int
) -> list[LeaveOneOut]:
    robust_all = _robust_set(full)
    out: list[LeaveOneOut] = []
    for lab in m.labels:
        rest = [x for x in m.labels if x != lab]
        t = gene_table(m.subset(rest), params, min_studies=min(min_studies, len(rest)))
        robust = _robust_set(t)
        out.append(
            LeaveOneOut(
                member=lab,
                n_robust_without=len(robust),
                robust_retained=(len(robust_all & robust) / len(robust_all)) if robust_all else 1.0,
                spearman_pooled_z=_spearman_z(full, t),
            )
        )
    return out


def _wide_table(table: pd.DataFrame, m: EffectMatrices) -> pd.DataFrame:
    wide = table.copy()
    wide["robust"] = table["robust"].astype(bool)
    for lab in m.labels:
        wide[f"lfc__{lab}"] = m.lfc[lab]
        wide[f"padj__{lab}"] = m.padj[lab]
    return wide


def run_comparison(
    run_dirs: Sequence[str | Path],
    out_dir: str | Path,
    *,
    name: str,
    question: str,
    case_label: str,
    control_label: str,
    params: CompareParams | None = None,
    strata: dict[str, str] | None = None,
) -> ComparisonReport:
    """``strata`` maps run label (``GSE:contrast``) or GSE to a stratum slug."""
    params = params or CompareParams()
    strata = strata or {}
    bad = [s for s in strata.values() if not _SLUG_RE.match(s)]
    if bad:
        raise ValueError(f"stratum names must be slugs ({SLUG}); got {bad}")
    final = Path(out_dir)
    _check_output_dir(final)
    work = final.parent / f".{final.name}.tmp-{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)
    report = ComparisonReport(
        name=name,
        question=question,
        case_label=case_label,
        control_label=control_label,
        status="complete",
        created_at=datetime.now(UTC),
        versions=_versions(),
        params=params.model_dump(),
    )
    try:
        _run(report, [Path(p) for p in run_dirs], work, params, strata)
    except Exception as exc:
        report.status = "failed"
        report.error = f"{type(exc).__name__}: {exc}"
        (work / "error.txt").write_text(traceback.format_exc())
        report.files["error"] = "error.txt"
    report.files["comparison_json"] = COMPARISON_JSON
    report.files["comparison_md"] = "comparison.md"
    (work / COMPARISON_JSON).write_text(report.model_dump_json(indent=2))
    (work / "comparison.md").write_text(render_markdown(report))
    if final.exists():
        shutil.rmtree(final)
    work.rename(final)
    return report


def _stratum_of(r: RunData, strata: dict[str, str]) -> str | None:
    return strata.get(r.label) or strata.get(r.report.gse)


def _load_all(run_dirs: list[Path]) -> tuple[list[RunData], list[Exclusion]]:
    runs: list[RunData] = []
    excluded: list[Exclusion] = []
    for d in run_dirs:
        if not (d / "report.json").exists():
            excluded.append(
                Exclusion(label=str(d), run_dir=str(d), reason="missing", detail="no report.json")
            )
            continue
        try:
            runs.append(load_run(d))
        except Exception as exc:
            excluded.append(
                Exclusion(
                    label=str(d),
                    run_dir=str(d),
                    reason="unreadable",
                    detail=f"{type(exc).__name__}: {exc}",
                )
            )
    return runs, excluded


def _run(
    report: ComparisonReport,
    run_dirs: list[Path],
    out: Path,
    params: CompareParams,
    strata: dict[str, str],
) -> None:
    runs, load_excluded = _load_all(run_dirs)
    g = gate(runs, params, strata)
    report.excluded = [*load_excluded, *g.excluded]
    report.concordance = g.concordance
    report.questions = g.questions
    report.warnings.extend(g.warnings)
    report.members = [_member(r, g, _stratum_of(r, strata)) for r in g.included]

    pd.DataFrame([e.model_dump() for e in report.excluded]).to_csv(
        out / "excluded.tsv", sep="\t", index=False
    )
    report.files["excluded"] = "excluded.tsv"
    if g.concordance:
        pd.DataFrame(
            g.concordance.spearman, index=g.concordance.members, columns=g.concordance.members
        ).to_csv(out / "concordance.tsv", sep="\t", float_format="%.4f")
        report.files["concordance"] = "concordance.tsv"
    if report.questions:
        (out / "questions.md").write_text(
            "# Questions\n\n" + "\n".join(f"- {q}" for q in report.questions) + "\n"
        )
        report.files["questions"] = "questions.md"

    pooled_runs = [r for r in g.included if r.label in g.pooled]
    flags = {lab: fl for lab, fl in g.flags.items() if fl}
    if len(pooled_runs) < 2:
        report.status = "insufficient"
        report.warnings.append(
            f"{len(pooled_runs)} dataset(s) in the default pool; a comparison needs at least 2"
        )
        _write_members(report, out)
        if params.figures and g.concordance and len(g.concordance.members) >= 2:
            p = figures.concordance_heatmap(
                g.concordance, out / "figures" / "concordance.png", flags
            )
            report.figures["concordance"] = str(p.relative_to(out))
        return

    all_m = EffectMatrices(g.included)
    m = all_m.subset([r.label for r in pooled_runs])
    min_studies = min(params.min_studies, len(pooled_runs))
    report.effective_min_studies = min_studies
    if min_studies < params.min_studies:
        report.warnings.append(
            f"only {len(pooled_runs)} datasets: pooling genes tested in >= {min_studies} instead "
            f"of {params.min_studies}; the same minimum applies to gene lookups"
        )
    table = gene_table(m, params, min_studies=min_studies)
    share = table.attrs["weight_share"].mean(axis=0, skipna=True)
    for mem in report.members:
        v = share.get(mem.label)
        mem.weight_share = None if v is None or np.isnan(v) else float(v)
    report.genes = synthesize(table, m.labels, params, min_studies=min_studies)
    _wide_table(table, m).to_csv(out / "gene_table.tsv", sep="\t", float_format="%.5g")
    report.files["gene_table"] = "gene_table.tsv"

    # Strata: pooled again within each sub-question with at least two pooled members.
    by_stratum: dict[str, list[str]] = {}
    for mem in report.members:
        if mem.stratum and mem.pooled:
            by_stratum.setdefault(mem.stratum, []).append(mem.label)
    if len(by_stratum) >= 2:
        strata_dir = _inside(out, out / "strata")
        strata_dir.mkdir(exist_ok=True)
        for s_name, labels in sorted(by_stratum.items()):
            if len(labels) < 2:
                report.warnings.append(f"stratum {s_name!r} has one pooled dataset; not pooled")
                continue
            ms = min(params.min_studies, len(labels))
            sub = m.subset(labels)
            t = gene_table(sub, params, min_studies=ms)
            report.strata[s_name] = synthesize(t, labels, params, min_studies=ms)
            path = _inside(out, strata_dir / f"{s_name}.tsv")
            _wide_table(t, sub).to_csv(path, sep="\t", float_format="%.5g")
            report.files[f"stratum_{s_name}"] = f"strata/{s_name}.tsv"

    queries = list(dict.fromkeys([*params.genes_of_interest, *(x.symbol for x in params.markers)]))
    lookups = lookup_across(queries, table, m, params, min_studies) if queries else []
    wanted = set(params.genes_of_interest)
    report.gene_lookup = [r for r in lookups if r.query in wanted] or lookups
    if params.markers:
        report.markers = score_markers_across(params.markers, lookups)

    report.pathways = synthesize_pathways(pooled_runs)
    if report.pathways:
        rows = [
            {
                "term": t.term,
                "n_members": t.n_members,
                "mean_nes": t.mean_nes,
                "n_pos": t.n_pos,
                "n_neg": t.n_neg,
                "n_sig_fdr": t.n_sig_fdr,
                "consistency": t.consistency,
                **{f"nes__{k}": v for k, v in t.nes.items()},
            }
            for t in report.pathways.terms
        ]
        pd.DataFrame(rows).to_csv(
            out / "pathway_table.tsv", sep="\t", index=False, float_format="%.4f"
        )
        report.files["pathway_table"] = "pathway_table.tsv"

    if params.pooled_enrichment:
        ranked = pooled_z(table)
        report.pooled_enrichment_coverage = {
            "pooled": int(cast(Any, table["z"].notna()).sum()),
            "ranked": len(ranked),
        }
        try:
            enr_df, enr_summary = run_prerank(
                ranked,
                EnrichmentParams(
                    gene_sets=params.gene_sets, permutation_num=params.permutation_num
                ),
            )
            report.pooled_enrichment = enr_summary
            enr_df.to_csv(out / "pooled_enrichment.tsv", sep="\t", index=False)
            report.files["pooled_enrichment"] = "pooled_enrichment.tsv"
        except Exception as exc:
            report.warnings.append(f"pooled enrichment skipped: {type(exc).__name__}: {exc}")

    if len(pooled_runs) >= 3:
        report.leave_one_out = leave_one_out(m, table, params, min_studies)

    # Sensitivity: every flagged run with its membership reversed.
    robust_default = _robust_set(table)
    for lab, fl in flags.items():
        for flag in fl:
            if flag not in ("labels_reversed", "low_concordance"):
                continue
            in_default = lab in g.pooled
            alt_labels = [x for x in m.labels if x != lab] if in_default else [*m.labels, lab]
            if len(alt_labels) < 2:
                continue
            alt = gene_table(
                all_m.subset(alt_labels),
                params,
                min_studies=min(params.min_studies, len(alt_labels)),
            )
            robust_alt = _robust_set(alt)
            union = robust_default | robust_alt
            report.sensitivity.append(
                Sensitivity(
                    member=lab,
                    flag=flag,
                    pooled_by_default=in_default,
                    n_robust_default=len(robust_default),
                    n_robust_alternative=len(robust_alt),
                    robust_jaccard=(len(robust_default & robust_alt) / len(union))
                    if union
                    else 1.0,
                    spearman_pooled_z=_spearman_z(table, alt),
                )
            )

    _write_members(report, out)

    if params.figures:
        fig_dir = out / "figures"
        if g.concordance and len(g.concordance.members) >= 2:
            report.figures["concordance"] = str(
                figures.concordance_heatmap(
                    g.concordance, fig_dir / "concordance.png", flags
                ).relative_to(out)
            )
        if report.pathways and report.pathways.terms:
            p = figures.nes_heatmap(report.pathways, fig_dir / "pathways.png")
            if p:
                report.figures["pathways"] = str(p.relative_to(out))
        if lookups:
            p = figures.forest(lookups, m.lfc, m.se, fig_dir / "forest.png")
            if p:
                report.figures["forest"] = str(p.relative_to(out))


def _write_members(report: ComparisonReport, out: Path) -> None:
    pd.DataFrame([x.model_dump() for x in report.members]).to_csv(
        out / "members.tsv", sep="\t", index=False
    )
    report.files["members"] = "members.tsv"


def compare_query_set(
    qs: QuerySet,
    runs_root: str | Path,
    out_dir: str | Path,
    params: CompareParams | None = None,
) -> ComparisonReport:
    """Resolve a QuerySet to ``runs_root/<GSE>/<contrast>`` directories and compare them.

    Missing or unreadable members are recorded as excluded, not raised.
    """
    params = (params or CompareParams()).model_copy(
        update={
            "genes_of_interest": list(
                dict.fromkeys(
                    [*(params.genes_of_interest if params else []), *qs.genes_of_interest]
                )
            ),
            "markers": [*(params.markers if params else []), *qs.markers],
        }
    )
    root = Path(runs_root)
    dirs = [root / mbr.gse / mbr.contrast for mbr in qs.members]
    strata = {f"{mbr.gse}:{mbr.contrast}": mbr.stratum for mbr in qs.members if mbr.stratum}
    return run_comparison(
        dirs,
        out_dir,
        name=qs.name,
        question=qs.question,
        case_label=qs.case_label,
        control_label=qs.control_label,
        params=params,
        strata=strata,
    )

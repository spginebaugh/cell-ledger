"""The standard two-group pipeline: load, reconcile, QC, filter, DE, enrichment, report.

One fixed sequence with a small set of parameters. The agent picks the dataset,
the contrast and the parameters; it does not write code.

Output is atomic: the run writes into a temporary sibling directory and swaps it
into place at the end, so a folder never mixes artifacts from two runs. Any
exception is caught, recorded in the report (``status=blocked``, ``error``), and
the report is still written.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import traceback
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
from pydantic import BaseModel, Field

from cell_ledger.analysis.annotation import load_annotation
from cell_ledger.analysis.bundle import build_anndata, load_counts, obs_frame, var_frame
from cell_ledger.analysis.de import DeParams, run_de
from cell_ledger.analysis.enrichment import HALLMARK, EnrichmentParams, run_prerank
from cell_ledger.analysis.filtering import filter_genes
from cell_ledger.analysis.genes import log2_normalized, lookup_genes, score_markers
from cell_ledger.analysis.qc import run_qc
from cell_ledger.analysis.steps import step
from cell_ledger.report import figures
from cell_ledger.report.models import AnalysisReport, MarkerExpectation, QcResult
from cell_ledger.report.render import render_markdown
from cell_ledger.samplesheet import Contrast, SampleSheet

REPORT_JSON = "report.json"


class PipelineParams(BaseModel):
    min_per_group: int = Field(default=3, ge=2)
    min_count: int = 10
    alpha: float = 0.05
    lfc_threshold: float = 1.0
    lfc_shrink: bool = True
    run_enrichment: bool = True
    gene_sets: str = HALLMARK
    permutation_num: int = 1000
    genes_of_interest: list[str] = Field(default_factory=list)
    markers: list[MarkerExpectation] = Field(default_factory=list)
    marker_top_n: int = 200
    top_n_genes: int = 50
    figures: bool = True
    n_cpus: int | None = None
    low_library_size: float = 1e6


def _versions() -> dict[str, str]:
    out = {"python": platform.python_version()}
    for pkg in ("cell-ledger", "pydeseq2", "pandas", "numpy", "anndata", "gseapy"):
        try:
            out[pkg] = version(pkg)
        except Exception:
            out[pkg] = "unknown"
    return out


def _check_output_dir(final: Path) -> None:
    """Refuse to replace a directory we did not create."""
    if final.exists() and any(final.iterdir()) and not (final / REPORT_JSON).exists():
        raise ValueError(
            f"{final} exists, is not empty and holds no {REPORT_JSON}; refusing to overwrite it"
        )


def _attach_qc_to_obs(adata: ad.AnnData, qc: QcResult) -> None:
    """Put per-sample QC into ``obs`` (and PCA into ``obsm``) so h5ad and samples.csv agree."""
    obs = obs_frame(adata)
    by = {s.gsm: s for s in qc.samples}
    idx = [str(g) for g in adata.obs_names]
    obs["library_size"] = [by[g].library_size for g in idx]
    obs["detected_genes"] = [by[g].detected_genes for g in idx]
    obs["pct_mito"] = [by[g].pct_mito for g in idx]
    obs["pct_ribo"] = [by[g].pct_ribo for g in idx]
    obs["mean_corr_same_arm"] = [
        np.nan if by[g].mean_corr_same_arm is None else by[g].mean_corr_same_arm for g in idx
    ]
    obs["mean_corr_other_arm"] = [
        np.nan if by[g].mean_corr_other_arm is None else by[g].mean_corr_other_arm for g in idx
    ]
    obs["predicted_sex"] = [by[g].predicted_sex or "" for g in idx]
    obs["qc_flags"] = [";".join(by[g].flags) for g in idx]
    if qc.pca is not None:
        coords = np.array([qc.pca.coords[g] for g in idx], dtype=float)
        adata.obsm["X_pca"] = coords
        obs["pc1"], obs["pc2"] = coords[:, 0], coords[:, 1]


def run_pipeline(
    *,
    counts_path: str | Path,
    annotation_path: str | Path,
    sheet: SampleSheet,
    contrast: Contrast,
    out_dir: str | Path,
    params: PipelineParams | None = None,
) -> AnalysisReport:
    params = params or PipelineParams()
    final = Path(out_dir)
    _check_output_dir(final)
    work = final.parent / f".{final.name}.tmp-{os.getpid()}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    report = AnalysisReport(
        gse=sheet.gse,
        contrast=contrast,
        status="complete",
        created_at=datetime.now(UTC),
        versions=_versions(),
        params=params.model_dump(),
    )
    try:
        _run(report, counts_path, annotation_path, sheet, contrast, work, params)
    except Exception as exc:
        report.status = "blocked"
        report.error = f"{type(exc).__name__}: {exc}"
        report.blockers.append(f"pipeline stopped: {report.error}")
        (work / "error.txt").write_text(traceback.format_exc())
        report.files["error"] = "error.txt"
    report.files["report_json"] = REPORT_JSON
    report.files["report_md"] = "report.md"
    (work / REPORT_JSON).write_text(report.model_dump_json(indent=2))
    (work / "report.md").write_text(render_markdown(report))
    if final.exists():
        shutil.rmtree(final)
    work.rename(final)
    return report


def _run(
    report: AnalysisReport,
    counts_path: str | Path,
    annotation_path: str | Path,
    sheet: SampleSheet,
    contrast: Contrast,
    out: Path,
    params: PipelineParams,
) -> None:
    steps = report.steps

    def rel(p: Path) -> str:
        return str(p.relative_to(out))

    # 1. Contract: blockers stop DE, qualifications travel with the result.
    blockers = contrast.problems(sheet, min_per_group=params.min_per_group)
    if blockers:
        report.status = "blocked"
        report.blockers.extend(blockers)
    report.qualifications.extend(contrast.qualifications(sheet))

    # 2. Load and reconcile.
    with step(steps, "load", counts=str(counts_path), annotation=str(annotation_path)):
        counts = load_counts(counts_path)
        annotation = load_annotation(annotation_path)
        adata, rec = build_anndata(counts, sheet, annotation, contrast)
        report.reconciliation = rec
    if rec.contrast_gsms_missing_from_counts:
        report.warnings.append(
            f"{len(rec.contrast_gsms_missing_from_counts)} contrast GSMs have no counts column "
            f"and were dropped: {rec.contrast_gsms_missing_from_counts}"
        )
    if rec.contrast_gsms_missing_from_sheet:
        report.warnings.append(
            f"{len(rec.contrast_gsms_missing_from_sheet)} contrast GSMs are not in the sample "
            f"sheet and were dropped: {rec.contrast_gsms_missing_from_sheet}"
        )
    if rec.columns_not_in_sheet:
        report.warnings.append(
            f"{len(rec.columns_not_in_sheet)} counts columns are not in the sample sheet "
            f"and were ignored: {rec.columns_not_in_sheet}"
        )
    if report.status == "complete" and (
        rec.n_case < params.min_per_group or rec.n_control < params.min_per_group
    ):
        report.status = "qc_only"
        report.blockers.append(
            f"after reconciliation only {rec.n_case} case / {rec.n_control} control samples "
            f"have counts; need {params.min_per_group} per group for DE"
        )

    counts_used = counts[rec.gsms_used]
    counts_used.index.name = "GeneID"
    counts_used.to_csv(out / "counts.tsv", sep="\t")
    report.files["counts"] = "counts.tsv"

    # 3. QC whenever there is something to compare.
    qc = None
    if adata.n_obs >= 2:
        with step(steps, "qc", low_library_size=params.low_library_size):
            qc = run_qc(adata, low_library_size=params.low_library_size)
            report.qc = qc
            _attach_qc_to_obs(adata, qc)
        if qc.flags:
            report.warnings.append(f"QC flags: {', '.join(qc.flags)}")
    elif report.status == "complete":
        report.status = "blocked"
        report.blockers.append("fewer than 2 samples with counts; nothing to analyse")
    samples = obs_frame(adata).copy()
    samples.index.name = "gsm"
    samples.to_csv(out / "samples.csv")
    report.files["samples"] = "samples.csv"

    # 4-6. Filter, DE, enrichment: only when the design allows it.
    results = normed = None
    arms = pd.Series(obs_frame(adata)["arm"].astype(str).to_numpy(), index=adata.obs_names)
    filtered = adata
    if report.status == "complete":
        with step(steps, "filter_genes", min_count=params.min_count):
            filtered, fsum = filter_genes(adata, min_count=params.min_count)
            report.filtering = fsum
        if filtered.n_vars == 0:
            report.status = "qc_only"
            report.blockers.append(
                f"no gene has >= {fsum.min_count} counts in >= {fsum.min_samples} samples; "
                "nothing to test"
            )
    if report.status == "complete":
        de_params = DeParams(
            alpha=params.alpha,
            lfc_threshold=params.lfc_threshold,
            lfc_shrink=params.lfc_shrink,
            n_cpus=params.n_cpus,
            top_n=params.top_n_genes,
            min_per_group=params.min_per_group,
        )
        with step(steps, "deseq2", blocking=contrast.blocking, **de_params.model_dump()) as rec_de:
            results, normed, de_summary, plan = run_de(
                filtered, de_params, blocking=contrast.blocking
            )
            report.de = de_summary
        report.warnings.extend(plan.warnings)
        report.warnings.extend(f"pydeseq2: {w}" for w in rec_de.warnings)
        if plan.pairing == "ignored":
            report.qualifications.append(
                f"contrast declares pairing by {contrast.blocking!r} but it could not be "
                "modelled; samples were treated as independent"
            )
        if plan.dropped:
            filtered = filtered[plan.kept].copy()
            arms = arms.loc[plan.kept]
        results.to_csv(out / "de_results.tsv", sep="\t")
        report.files["de_results"] = "de_results.tsv"
        normed_t = normed.T
        normed_t.index.name = "GeneID"
        normed_t.to_csv(out / "normalized_counts.tsv", sep="\t", float_format="%.3f")
        report.files["normalized_counts"] = "normalized_counts.tsv"
        filtered.layers["normed_counts"] = normed.loc[
            filtered.obs_names, filtered.var_names
        ].to_numpy()
        filtered.layers["log2_normed"] = (
            log2_normalized(normed).loc[filtered.obs_names, filtered.var_names].to_numpy()
        )

        if params.run_enrichment:
            enr = EnrichmentParams(
                gene_sets=params.gene_sets, permutation_num=params.permutation_num
            )
            try:
                with step(steps, "gsea_prerank", **enr.model_dump()):
                    enr_df, enr_summary = run_prerank(results, enr)
                    report.enrichment = enr_summary
                enr_df.to_csv(out / "enrichment.tsv", sep="\t", index=False)
                report.files["enrichment"] = "enrichment.tsv"
            except Exception as exc:
                report.warnings.append(f"enrichment skipped: {type(exc).__name__}: {exc}")

    # 7. Gene-centric answers and marker scoring (work in every status).
    queries = list(dict.fromkeys([*params.genes_of_interest, *(m.symbol for m in params.markers)]))
    if queries:
        with step(steps, "gene_lookup", n=len(queries)):
            lookups = lookup_genes(
                queries,
                var_frame(adata),
                results=results,
                normed=normed,
                arms=arms,
                alpha=params.alpha,
            )
            wanted = set(params.genes_of_interest)
            report.gene_lookup = [r for r in lookups if r.query in wanted] or lookups
            if params.markers:
                report.markers = score_markers(params.markers, lookups, top_n=params.marker_top_n)
        pd.DataFrame([r.model_dump() for r in lookups]).to_csv(out / "gene_lookup.csv", index=False)
        report.files["gene_lookup"] = "gene_lookup.csv"

    # 8. Figures.
    if params.figures:
        with step(steps, "figures"):
            fig_dir = out / "figures"
            if qc is not None:
                report.figures["library_sizes"] = rel(
                    figures.library_sizes(
                        qc, fig_dir / "library_sizes.png", params.low_library_size
                    )
                )
                if qc.pca is not None:
                    report.figures["pca"] = rel(figures.pca(qc, fig_dir / "pca.png"))
            if results is not None:
                report.figures["volcano"] = rel(
                    figures.volcano(
                        results,
                        fig_dir / "volcano.png",
                        alpha=params.alpha,
                        lfc_threshold=params.lfc_threshold,
                    )
                )
                if normed is not None and report.gene_lookup:
                    p = figures.genes_of_interest(
                        log2_normalized(normed),
                        arms,
                        report.gene_lookup,
                        fig_dir / "genes_of_interest.png",
                    )
                    if p is not None:
                        report.figures["genes_of_interest"] = rel(p)
            if report.enrichment is not None:
                p = figures.enrichment_bars(report.enrichment, fig_dir / "enrichment.png")
                if p is not None:
                    report.figures["enrichment"] = rel(p)

    # 9. AnnData. report.json is canonical; the embedded copy lacks only this step's timing.
    with step(steps, "write_h5ad"):
        report.files["anndata"] = "dataset.h5ad"
        report.files["report_json"] = REPORT_JSON
        report.files["report_md"] = "report.md"
        filtered.uns["report"] = report.model_dump_json()
        filtered.write_h5ad(out / "dataset.h5ad")


def load_design(path: str | Path) -> tuple[SampleSheet, list[Contrast], list[MarkerExpectation]]:
    """Read a design file: ``{"samplesheet": ..., "contrasts": [...], "markers": [...]}``."""
    doc = json.loads(Path(path).read_text())
    sheet = SampleSheet.model_validate(doc["samplesheet"])
    contrasts = [Contrast.model_validate(c) for c in doc.get("contrasts", [])]
    markers = [MarkerExpectation.model_validate(m) for m in doc.get("markers", [])]
    return sheet, contrasts, markers

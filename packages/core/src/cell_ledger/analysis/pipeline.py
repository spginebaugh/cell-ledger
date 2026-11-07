"""The standard two-group pipeline: load, reconcile, QC, filter, DE, enrichment, report.

One fixed sequence with a small set of parameters. The agent picks the dataset,
the contrast and the parameters; it does not write code.
"""

from __future__ import annotations

import json
import platform
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path

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
from cell_ledger.report.models import AnalysisReport, MarkerExpectation
from cell_ledger.report.render import render_markdown
from cell_ledger.samplesheet import Contrast, SampleSheet


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
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    report = AnalysisReport(
        gse=sheet.gse,
        contrast=contrast,
        status="complete",
        created_at=datetime.now(UTC),
        versions=_versions(),
        params=params.model_dump(),
    )
    steps = report.steps  # pydantic copies on construction; append to the report's own list

    def rel(p: Path) -> str:
        return str(p.relative_to(out))

    # 1. Contract-level blockers (before touching any data).
    blockers = contrast.problems(sheet, min_per_group=params.min_per_group)
    if blockers:
        report.status = "blocked"
        report.blockers.extend(blockers)

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
    if rec.columns_not_in_sheet:
        report.warnings.append(
            f"{len(rec.columns_not_in_sheet)} counts columns are not in the sample sheet "
            f"and were ignored: {rec.columns_not_in_sheet}"
        )
    if report.status != "blocked" and (
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

    # 3. QC (always, when there is anything to look at).
    qc = None
    if adata.n_obs >= 2:
        with step(steps, "qc", low_library_size=params.low_library_size):
            qc = run_qc(adata, low_library_size=params.low_library_size)
            report.qc = qc
        if qc.flags:
            report.warnings.append(f"QC flags: {', '.join(qc.flags)}")
        qc_df = pd.DataFrame([s.model_dump() for s in qc.samples]).set_index("gsm")
        qc_df["flags"] = qc_df["flags"].map(lambda f: ";".join(f))
        samples = obs_frame(adata).join(qc_df.drop(columns=["arm"]), how="left")
        if qc.pca is not None:
            samples["pc1"] = [qc.pca.coords[g][0] for g in samples.index]
            samples["pc2"] = [qc.pca.coords[g][1] for g in samples.index]
    else:
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
        de_params = DeParams(
            alpha=params.alpha,
            lfc_threshold=params.lfc_threshold,
            lfc_shrink=params.lfc_shrink,
            n_cpus=params.n_cpus,
            top_n=params.top_n_genes,
        )
        with step(steps, "deseq2", **de_params.model_dump()) as rec_de:
            results, normed, de_summary = run_de(filtered, de_params)
            report.de = de_summary
        report.warnings.extend(f"pydeseq2: {w}" for w in rec_de.warnings)
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
            report.gene_lookup = [
                r for r in lookups if r.query in params.genes_of_interest
            ] or lookups
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

    # 9. Persist: AnnData, JSON report, Markdown.
    with step(steps, "write"):
        filtered.uns["report"] = report.model_dump_json()
        filtered.write_h5ad(out / "dataset.h5ad")
        report.files["anndata"] = "dataset.h5ad"
        (out / "report.json").write_text(report.model_dump_json(indent=2))
        report.files["report_json"] = "report.json"
        (out / "report.md").write_text(render_markdown(report))
        report.files["report_md"] = "report.md"
    (out / "report.json").write_text(report.model_dump_json(indent=2))
    (out / "report.md").write_text(render_markdown(report))
    return report


def load_design(path: str | Path) -> tuple[SampleSheet, list[Contrast], list[MarkerExpectation]]:
    """Read a design file: ``{"samplesheet": ..., "contrasts": [...], "markers": [...]}``."""
    doc = json.loads(Path(path).read_text())
    sheet = SampleSheet.model_validate(doc["samplesheet"])
    contrasts = [Contrast.model_validate(c) for c in doc.get("contrasts", [])]
    markers = [MarkerExpectation.model_validate(m) for m in doc.get("markers", [])]
    return sheet, contrasts, markers

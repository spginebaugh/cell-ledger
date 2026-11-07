"""The standard two-group pipeline: load, reconcile, QC, filter, DE, enrichment, report.

One fixed sequence with a small set of parameters. The agent picks the dataset,
the contrast and the parameters; it does not write code.

Output is atomic: the run writes into a temporary sibling directory and swaps it
into place at the end, so a folder never mixes artifacts from two runs. Any
exception is caught, recorded in the report (``status=blocked``, ``error``), and
the report is still written.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import platform
import shutil
import traceback
from collections import Counter
from datetime import UTC, datetime
from importlib.metadata import version
from pathlib import Path
from typing import Any

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
from cell_ledger.analysis.steps import emit, step
from cell_ledger.report import figures
from cell_ledger.report.models import AnalysisReport, GeneExpression, MarkerExpectation, QcResult
from cell_ledger.report.render import render_markdown
from cell_ledger.samplesheet import Contrast, SampleSheet

REPORT_JSON = "report.json"
CONTEXT_FIELDS = ("tissue", "cell_type", "cell_line", "treatment", "time_point", "organism")


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
    """Put per-sample QC into ``obs`` (and PCA into ``obsm``) so samples.csv carries them."""
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


def summarize_context(sheet: SampleSheet, gsms: list[str]) -> dict[str, str]:
    """Modal non-empty value of each context field over ``gsms``, when it covers >= half of them."""
    out: dict[str, str] = {}
    samples = [sheet.by_gsm(g) for g in gsms if g in set(sheet.gsms)]
    for field in CONTEXT_FIELDS:
        values = [v for v in (getattr(s, field) for s in samples) if v]
        if not values:
            continue
        top, n = Counter(values).most_common(1)[0]
        if n * 2 >= len(samples):
            out[field] = top
    return out


def _file_digest(path: str | Path) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def code_digest() -> str:
    """sha256 over the analysis, report and samplesheet sources: a code change without a
    version bump still invalidates cached runs."""
    root = Path(__file__).resolve().parent.parent
    h = hashlib.sha256()
    for sub_dir in ("analysis", "report", "samplesheet"):
        for f in sorted((root / sub_dir).glob("*.py")):
            h.update(f.name.encode())
            h.update(f.read_bytes())
    return h.hexdigest()


def compute_fingerprint(
    counts_path: str | Path,
    annotation_path: str | Path,
    sheet: SampleSheet,
    contrast: Contrast,
    params: PipelineParams,
) -> str:
    """sha256 of everything a run depends on: input files, design, parameters, library
    versions and the analysis code itself."""
    h = hashlib.sha256()
    h.update(_file_digest(counts_path).encode())
    h.update(_file_digest(annotation_path).encode())
    h.update(sheet.model_dump_json().encode())
    h.update(contrast.model_dump_json().encode())
    h.update(params.model_dump_json().encode())
    h.update(json.dumps(_versions(), sort_keys=True).encode())
    h.update(code_digest().encode())
    return h.hexdigest()


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
    emit("run", status="started", gse=sheet.gse)
    try:
        report.fingerprint = compute_fingerprint(
            counts_path, annotation_path, sheet, contrast, params
        )
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
    emit("run", status="finished", gse=sheet.gse, result=report.status)
    return report


VOLCANO_COLUMNS = ("gene_id", "symbol", "base_mean", "log2fc", "padj")


def write_volcano(results: pd.DataFrame, path: Path, *, alpha: float, lfc_threshold: float) -> None:
    """The DE table the browser draws: five columns, column-major, gzipped JSON.

    Column-major keeps the file small and parses straight into typed arrays. Numbers are
    rounded to what a plot can show; the full-precision table stays in ``de_results.tsv``.
    """
    df = results.reset_index()
    if "gene_id" not in df.columns:
        df = df.rename(columns={df.columns[0]: "gene_id"})

    def column(name: str, nd: int | None) -> list[Any]:
        out: list[Any] = []
        for v in df[name].tolist():
            if v is None or (isinstance(v, float) and np.isnan(v)):
                out.append(None)
            elif nd is None:
                out.append(str(v))
            else:
                out.append(round(float(v), nd))
        return out

    doc = {
        "n": len(df),
        "alpha": alpha,
        "lfc_threshold": lfc_threshold,
        "columns": list(VOLCANO_COLUMNS),
        "gene_id": column("gene_id", None),
        "symbol": column("symbol", None),
        "base_mean": column("base_mean", 2),
        "log2fc": column("log2fc", 4),
        # padj spans 300 orders of magnitude: 3 significant digits, never rounded to a
        # fixed number of decimals (that would turn 1e-282 into 0).
        "padj": [None if v is None else float(f"{v:.3g}") for v in column("padj", 300)],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)


HEATMAP_GENES = 50


def _cluster_order(x: np.ndarray) -> list[int]:
    """Row order from average-linkage hierarchical clustering on correlation distance.

    Falls back to the given order when there is nothing to cluster or the distances are
    degenerate (constant rows), so the artifact is always written.
    """
    n = x.shape[0]
    if n < 3:
        return list(range(n))
    try:
        from scipy.cluster.hierarchy import leaves_list, linkage, optimal_leaf_ordering
        from scipy.spatial.distance import pdist

        d = pdist(x, metric="correlation")
        if not np.all(np.isfinite(d)):
            return list(range(n))
        link = linkage(d, method="average")
        return [int(i) for i in leaves_list(optimal_leaf_ordering(link, d))]
    except Exception:
        return list(range(n))


def write_heatmap(
    results: pd.DataFrame,
    log2n: pd.DataFrame,
    arms: pd.Series,
    path: Path,
    *,
    alpha: float,
    lfc_threshold: float,
    n_genes: int = HEATMAP_GENES,
) -> int:
    """The expression heatmap the browser draws: the top genes by adjusted p (half from each
    direction, with the fold-change floor when enough genes pass it), z-scored per gene over
    the fitted observations, both axes ordered by hierarchical clustering.

    Clustering is blind to the arms: the arm bar the browser draws on top is how the reader
    judges whether the groups separate. Returns the number of genes written (0 writes nothing).
    """
    tested: pd.DataFrame = results.loc[results["padj"].notna() & (results["padj"] < alpha)]
    sig: pd.DataFrame = tested.loc[tested.index.isin(log2n.columns)]

    def top(direction: int) -> pd.DataFrame:
        lfc = sig["log2fc"].to_numpy(dtype=float)
        side: pd.DataFrame = sig.loc[np.sign(lfc) == direction]
        side_lfc = side["log2fc"].to_numpy(dtype=float)
        strong: pd.DataFrame = side.loc[np.abs(side_lfc) >= lfc_threshold]
        pool = strong if len(strong) >= n_genes // 2 else side
        ranked = pool.assign(_a=np.abs(pool["log2fc"].to_numpy(dtype=float)))
        return ranked.sort_values(["padj", "_a"], ascending=[True, False])

    up, down = top(1), top(-1)
    half = n_genes // 2
    chosen = pd.concat([up.head(half), down.head(half)])
    # when one direction is short, let the other fill the remaining rows
    if len(chosen) < n_genes:
        rest = pd.concat([up.iloc[half:], down.iloc[half:]]).sort_values("padj")
        chosen = pd.concat([chosen, rest.head(n_genes - len(chosen))])
    if len(chosen) < 2:
        return 0
    gene_ids = [str(g) for g in chosen.index]
    x = log2n[gene_ids].to_numpy(dtype=float).T  # genes x samples
    mu = x.mean(axis=1, keepdims=True)
    sd = x.std(axis=1, keepdims=True)
    sd[sd == 0] = 1.0
    z = (x - mu) / sd
    row_order = _cluster_order(z)
    col_order = _cluster_order(z.T)
    samples = [str(s) for s in log2n.index]
    doc = {
        "n_genes": len(gene_ids),
        "n_samples": len(samples),
        "alpha": alpha,
        "lfc_threshold": lfc_threshold,
        "genes": [
            {
                "gene_id": gid,
                "symbol": None
                if pd.isna(chosen.at[gid, "symbol"])
                else str(chosen.at[gid, "symbol"]),
                "log2fc": round(float(chosen.at[gid, "log2fc"]), 3),
                "padj": float(f"{float(chosen.at[gid, 'padj']):.3g}"),
            }
            for gid in gene_ids
        ],
        "samples": [{"id": s, "arm": str(arms.get(s, ""))} for s in samples],
        "row_order": row_order,
        "col_order": col_order,
        # z-scores, row-major (gene then sample), 2 decimals; log2 values alongside for hover
        "z": [[round(float(v), 2) for v in row] for row in z],
        "log2": [[round(float(v), 2) for v in row] for row in x],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8", compresslevel=6) as f:
        json.dump(doc, f, separators=(",", ":"), allow_nan=False)
    return len(gene_ids)


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
        report.context = summarize_context(sheet, rec.gsms_used)
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
            fit = run_de(filtered, de_params, blocking=contrast.blocking)
            results, normed, plan = fit.results, fit.normed, fit.plan
            report.de = fit.summary
        report.warnings.extend(plan.warnings)
        report.warnings.extend(f"pydeseq2: {w}" for w in rec_de.warnings)
        if plan.pairing == "ignored":
            report.qualifications.append(
                f"contrast declares pairing by {contrast.blocking!r} but it could not be "
                "modelled; samples were treated as independent"
            )
        if plan.unmodelled_dependence:
            report.qualifications.append(plan.unmodelled_dependence)
        if plan.collapsed:
            n = sum(len(v) for v in plan.collapsed.values())
            report.qualifications.append(
                f"{n} samples repeat a {contrast.blocking} within an arm and were summed into "
                f"{len(plan.collapsed)} observations before the fit; the fit has "
                f"{fit.summary.summary.n_case_used} case and "
                f"{fit.summary.summary.n_control_used} control observations"
            )
        arms = fit.arms
        results.to_csv(out / "de_results.tsv", sep="\t")
        report.files["de_results"] = "de_results.tsv"
        write_volcano(
            results,
            out / "volcano.json.gz",
            alpha=params.alpha,
            lfc_threshold=params.lfc_threshold,
        )
        report.files["volcano"] = "volcano.json.gz"
        normed_t = normed.T
        normed_t.index.name = "GeneID"
        normed_t.to_csv(out / "normalized_counts.tsv", sep="\t", float_format="%.3f")
        report.files["normalized_counts"] = "normalized_counts.tsv"
        if (
            write_heatmap(
                results,
                log2_normalized(normed),
                arms,
                out / "heatmap.json.gz",
                alpha=params.alpha,
                lfc_threshold=params.lfc_threshold,
            )
            > 0
        ):
            report.files["heatmap"] = "heatmap.json.gz"

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
        if normed is not None:
            log2n = log2_normalized(normed)
            seen: set[str] = set()
            for r in lookups:
                gid = r.gene_id
                if gid is None or gid in seen or gid not in log2n.columns:
                    continue
                seen.add(gid)
                col = log2n[gid].to_numpy(dtype=float)
                report.gene_expression.append(
                    GeneExpression(
                        gene_id=gid,
                        symbol=r.symbol,
                        values={
                            str(g): round(float(v), 4)
                            for g, v in zip(log2n.index, col, strict=True)
                        },
                    )
                )

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


def load_design(path: str | Path) -> tuple[SampleSheet, list[Contrast], list[MarkerExpectation]]:
    """Read a design file: ``{"samplesheet": ..., "contrasts": [...], "markers": [...]}``."""
    doc = json.loads(Path(path).read_text())
    sheet = SampleSheet.model_validate(doc["samplesheet"])
    contrasts = [Contrast.model_validate(c) for c in doc.get("contrasts", [])]
    markers = [MarkerExpectation.model_validate(m) for m in doc.get("markers", [])]
    return sheet, contrasts, markers

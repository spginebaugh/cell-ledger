import gzip
import json

import pandas as pd
import pytest

from cell_ledger.analysis import PipelineParams, load_design, run_pipeline
from cell_ledger.analysis.enrichment import EnrichmentParams, run_prerank
from cell_ledger.report import AnalysisReport, render_markdown
from cell_ledger.report.models import MarkerExpectation
from cell_ledger.samplesheet import Contrast


def test_pipeline_end_to_end(synthetic, synthetic_files, tmp_path):
    out = tmp_path / "run"
    params = PipelineParams(
        run_enrichment=False,
        genes_of_interest=["G10", "NOPE"],
        markers=[
            MarkerExpectation(symbol="G10", direction="up"),
            MarkerExpectation(symbol="G60", direction="down"),
        ],
    )
    report = run_pipeline(
        counts_path=synthetic_files[0],
        annotation_path=synthetic_files[1],
        sheet=synthetic.sheet,
        contrast=synthetic.contrast,
        out_dir=out,
        params=params,
    )
    assert report.status == "complete"
    assert report.de is not None and report.de.summary.n_sig >= 80
    assert report.markers is not None and report.markers.n_recovered_sig == 2
    assert [r.verdict for r in report.gene_lookup] == ["up", "not_found"]
    assert any("GSM42" in w for w in report.warnings)
    for f in (
        "counts.tsv",
        "samples.csv",
        "de_results.tsv",
        "normalized_counts.tsv",
        "gene_lookup.csv",
        "volcano.json.gz",
        "heatmap.json.gz",
        "report.json",
        "report.md",
    ):
        assert (out / f).exists(), f
    for fig in ("library_sizes", "pca", "volcano", "genes_of_interest"):
        assert (out / report.figures[fig]).exists(), fig
    loaded = AnalysisReport.model_validate_json((out / "report.json").read_text())
    assert loaded.de is not None and loaded.de.summary.n_sig == report.de.summary.n_sig
    # The browser-side DE table: column-major, one entry per tested gene, nulls kept.
    with gzip.open(out / "volcano.json.gz", "rt") as f:
        volcano = json.load(f)
    assert volcano["n"] == report.de.summary.n_genes_tested == len(volcano["gene_id"])
    assert volcano["alpha"] == params.alpha and set(volcano["columns"]) == {
        "gene_id",
        "symbol",
        "base_mean",
        "log2fc",
        "padj",
    }
    assert "G10" in volcano["symbol"]
    assert min(p for p in volcano["padj"] if p is not None) > 0  # tiny padj must not round to 0
    # The browser-side heatmap: top genes z-scored over the fitted samples, both axes a
    # permutation from clustering, every sample carrying its arm.
    assert report.files["heatmap"] == "heatmap.json.gz"
    with gzip.open(out / "heatmap.json.gz", "rt") as f:
        heat = json.load(f)
    assert 2 <= heat["n_genes"] <= 50 and len(heat["genes"]) == heat["n_genes"]
    assert heat["n_samples"] == report.de.summary.n_case_used + report.de.summary.n_control_used
    assert sorted(heat["row_order"]) == list(range(heat["n_genes"]))
    assert sorted(heat["col_order"]) == list(range(heat["n_samples"]))
    assert len(heat["z"]) == heat["n_genes"] and len(heat["z"][0]) == heat["n_samples"]
    assert {s["arm"] for s in heat["samples"]} == {"case", "control"}
    assert any(g["log2fc"] > 0 for g in heat["genes"]) and any(
        g["log2fc"] < 0 for g in heat["genes"]
    )
    # Per-sample values for the looked-up genes (queries and markers), keyed by GSM.
    assert {e.symbol for e in report.gene_expression} == {"G10", "G60"}
    g10 = next(e for e in report.gene_expression if e.symbol == "G10")
    assert set(g10.values) == set(synthetic.contrast.gsms) - {"GSM42"}
    md = render_markdown(report)
    assert "Differential expression" in md and "G10" in md
    assert {s.name for s in report.steps} >= {
        "load",
        "qc",
        "filter_genes",
        "deseq2",
        "gene_lookup",
    }
    # samples.csv carries the QC columns next to the harmonized labels
    csv = pd.read_csv(out / "samples.csv", index_col=0)
    assert {"library_size", "qc_flags", "pc1", "evidence"} <= set(csv.columns)
    assert report.qc is not None
    assert sorted(csv["library_size"]) == sorted(s.library_size for s in report.qc.samples)
    assert report.de.summary.pairing == "none"  # the synthetic contrast sets no blocking
    assert report.qualifications == []


def test_pipeline_blocks_small_groups_but_still_runs_qc(synthetic, synthetic_files, tmp_path):
    c = synthetic.contrast
    small = Contrast(**{**c.model_dump(), "case_gsms": c.case_gsms[:2]})
    report = run_pipeline(
        counts_path=synthetic_files[0],
        annotation_path=synthetic_files[1],
        sheet=synthetic.sheet,
        contrast=small,
        out_dir=tmp_path / "blocked",
        params=PipelineParams(run_enrichment=False, figures=False),
    )
    assert report.status == "blocked"
    assert any("fewer than 3" in b for b in report.blockers)
    assert report.qc is not None and report.de is None
    assert "de_results" not in report.files and (tmp_path / "blocked" / "samples.csv").exists()


def test_pipeline_qc_only_when_counts_missing(synthetic, synthetic_files, tmp_path):
    """Contract says 3 vs 3 but only 2 cases have counts columns -> qc_only, not blocked."""
    c = synthetic.contrast
    thin = Contrast(**{**c.model_dump(), "case_gsms": ["GSM1", "GSM2", "GSM42"]})
    report = run_pipeline(
        counts_path=synthetic_files[0],
        annotation_path=synthetic_files[1],
        sheet=synthetic.sheet,
        contrast=thin,
        out_dir=tmp_path / "thin",
        params=PipelineParams(run_enrichment=False, figures=False),
    )
    assert report.status == "qc_only"
    assert report.reconciliation is not None
    assert report.reconciliation.n_case == 2 and report.de is None


def test_prerank_with_custom_gmt(synthetic, synthetic_files, tmp_path):
    from cell_ledger.analysis import (
        DeParams,
        build_anndata,
        filter_genes,
        load_annotation,
        load_counts,
        run_de,
    )

    counts = load_counts(synthetic_files[0])
    adata, _ = build_anndata(
        counts, synthetic.sheet, load_annotation(synthetic_files[1]), synthetic.contrast
    )
    filtered, _ = filter_genes(adata)
    results = run_de(filtered, DeParams(lfc_shrink=False)).results
    gmt = tmp_path / "sets.gmt"
    up_set = "\t".join(["PLANTED_UP", "test", *[f"G{g}" for g in synthetic.up]])
    down_set = "\t".join(["PLANTED_DOWN", "test", *[f"G{g}" for g in synthetic.down]])
    rand_set = "\t".join(["RANDOM", "test", *[f"G{g}" for g in range(200, 240)]])
    gmt.write_text("\n".join([up_set, down_set, rand_set]) + "\n")
    df, summary = run_prerank(
        results, EnrichmentParams(gene_sets=str(gmt), permutation_num=100, threads=1)
    )
    by = {t.term: t for t in summary.top}
    assert by["PLANTED_UP"].nes > 0 and by["PLANTED_DOWN"].nes < 0
    assert by["PLANTED_UP"].fdr < 0.05 and by["PLANTED_DOWN"].fdr < 0.05
    assert summary.n_terms == 3 and len(df) == 3


def test_load_design_reads_fixture():
    from pathlib import Path

    fixture = Path(__file__).parent / "fixtures" / "geo_examples" / "GSE82227.json"
    sheet, contrasts, markers = load_design(fixture)
    assert sheet.gse == "GSE82227" and contrasts[0].name == "ifng_vs_media_24h"
    assert isinstance(markers, list)


DATA = pytest.importorskip("pathlib").Path(__file__).parents[3] / "data" / "geo"


@pytest.mark.slow
def test_real_ifng_markers_recovered(tmp_path):
    counts = DATA / "GSE82227" / "GSE82227_raw_counts_GRCh38.p13_NCBI.tsv.gz"
    if not counts.exists():
        pytest.skip("local GEO data not downloaded")
    from pathlib import Path

    sheet, contrasts, markers = load_design(
        Path(__file__).parent / "fixtures" / "geo_examples" / "GSE82227.json"
    )
    report = run_pipeline(
        counts_path=counts,
        annotation_path=DATA / "annotation" / "Human.GRCh38.p13.annot.tsv.gz",
        sheet=sheet,
        contrast=contrasts[0],
        out_dir=tmp_path / "GSE82227",
        params=PipelineParams(
            run_enrichment=False,
            figures=False,
            markers=markers
            or [
                MarkerExpectation(symbol=s, direction="up")
                for s in ["CXCL9", "CXCL10", "CXCL11", "IDO1", "GBP1"]
            ],
        ),
    )
    assert report.status == "complete"
    assert report.markers is not None and report.markers.fraction_recovered >= 0.8


def _base(synthetic, synthetic_files):
    return dict(
        counts_path=synthetic_files[0], annotation_path=synthetic_files[1], sheet=synthetic.sheet
    )


QUICK = PipelineParams(run_enrichment=False, figures=False)


def test_rerun_replaces_stale_outputs(synthetic, synthetic_files, tmp_path):
    out = tmp_path / "run"
    run_pipeline(
        **_base(synthetic, synthetic_files), contrast=synthetic.contrast, out_dir=out, params=QUICK
    )
    assert (out / "de_results.tsv").exists()
    c = synthetic.contrast
    small = Contrast(**{**c.model_dump(), "case_gsms": c.case_gsms[:2]})
    report = run_pipeline(
        **_base(synthetic, synthetic_files), contrast=small, out_dir=out, params=QUICK
    )
    assert report.status == "blocked"
    assert not (out / "de_results.tsv").exists()
    assert not (out / "normalized_counts.tsv").exists()
    assert not list(tmp_path.glob(".run.tmp-*"))


def test_refuses_to_overwrite_foreign_directory(synthetic, synthetic_files, tmp_path):
    out = tmp_path / "mine"
    out.mkdir()
    (out / "notes.txt").write_text("precious")
    with pytest.raises(ValueError, match="refusing"):
        run_pipeline(**_base(synthetic, synthetic_files), contrast=synthetic.contrast, out_dir=out)
    assert (out / "notes.txt").read_text() == "precious"


def test_contrast_gsm_outside_sheet_still_writes_report(synthetic, synthetic_files, tmp_path):
    c = synthetic.contrast
    bad = Contrast(**{**c.model_dump(), "case_gsms": [*c.case_gsms, "GSM999"]})
    report = run_pipeline(
        **_base(synthetic, synthetic_files), contrast=bad, out_dir=tmp_path / "bad", params=QUICK
    )
    assert report.status == "blocked" and report.error is None
    assert report.reconciliation is not None
    assert report.reconciliation.contrast_gsms_missing_from_sheet == ["GSM999"]
    assert report.qc is not None
    assert (tmp_path / "bad" / "report.json").exists()


def test_empty_gene_filter_is_qc_only(synthetic, synthetic_files, tmp_path):
    params = PipelineParams(run_enrichment=False, figures=False, min_count=10**9)
    report = run_pipeline(
        **_base(synthetic, synthetic_files),
        contrast=synthetic.contrast,
        out_dir=tmp_path / "empty",
        params=params,
    )
    assert report.status == "qc_only" and report.de is None
    assert any("nothing to test" in b for b in report.blockers)


def test_unexpected_exception_is_reported_not_raised(synthetic, synthetic_files, tmp_path):
    report = run_pipeline(
        counts_path=tmp_path / "does_not_exist.tsv",
        annotation_path=synthetic_files[1],
        sheet=synthetic.sheet,
        contrast=synthetic.contrast,
        out_dir=tmp_path / "crash",
    )
    assert report.status == "blocked" and report.error and "FileNotFoundError" in report.error
    assert (tmp_path / "crash" / "error.txt").exists()
    saved = AnalysisReport.model_validate_json((tmp_path / "crash" / "report.json").read_text())
    assert saved.error == report.error


def test_uncertain_contrast_runs_qualified_and_proposed_is_blocked(
    synthetic, synthetic_files, tmp_path
):
    from cell_ledger.samplesheet import ContrastStatus

    c = synthetic.contrast.model_copy(
        update={"status": ContrastStatus.UNCERTAIN, "blocking": "donor"}
    )
    report = run_pipeline(
        **_base(synthetic, synthetic_files), contrast=c, out_dir=tmp_path / "unc", params=QUICK
    )
    assert report.status == "complete" and report.de is not None
    assert any("uncertain" in q for q in report.qualifications)
    assert report.de.summary.pairing == "modelled" and report.de.summary.design == "~block + arm"
    proposed = synthetic.contrast.model_copy(update={"status": ContrastStatus.PROPOSED})
    report = run_pipeline(
        **_base(synthetic, synthetic_files),
        contrast=proposed,
        out_dir=tmp_path / "prop",
        params=QUICK,
    )
    assert report.status == "blocked" and report.de is None


def test_fingerprint_tracks_inputs_design_params_and_code(synthetic, synthetic_files) -> None:
    from cell_ledger.analysis.pipeline import code_digest, compute_fingerprint

    base = compute_fingerprint(
        synthetic_files[0], synthetic_files[1], synthetic.sheet, synthetic.contrast, QUICK
    )
    same = compute_fingerprint(
        synthetic_files[0], synthetic_files[1], synthetic.sheet, synthetic.contrast, QUICK
    )
    assert base == same
    other_params = QUICK.model_copy(update={"alpha": 0.1})
    assert (
        compute_fingerprint(
            synthetic_files[0],
            synthetic_files[1],
            synthetic.sheet,
            synthetic.contrast,
            other_params,
        )
        != base
    )
    c = synthetic.contrast
    smaller = Contrast(**{**c.model_dump(), "case_gsms": c.case_gsms[:3]})
    assert (
        compute_fingerprint(synthetic_files[0], synthetic_files[1], synthetic.sheet, smaller, QUICK)
        != base
    )
    assert len(code_digest()) == 64

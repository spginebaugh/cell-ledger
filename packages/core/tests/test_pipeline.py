import json

import anndata as ad
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
        "dataset.h5ad",
        "report.json",
        "report.md",
    ):
        assert (out / f).exists(), f
    for fig in ("library_sizes", "pca", "volcano", "genes_of_interest"):
        assert (out / report.figures[fig]).exists(), fig
    loaded = AnalysisReport.model_validate_json((out / "report.json").read_text())
    assert loaded.de is not None and loaded.de.summary.n_sig == report.de.summary.n_sig
    adata = ad.read_h5ad(out / "dataset.h5ad")
    assert set(adata.layers) >= {"counts", "normed_counts", "log2_normed"}
    assert json.loads(adata.uns["report"])["gse"] == "GSE1"
    md = render_markdown(report)
    assert "Differential expression" in md and "G10" in md
    assert {s.name for s in report.steps} >= {
        "load",
        "qc",
        "filter_genes",
        "deseq2",
        "gene_lookup",
        "write",
    }


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
    results, _, _ = run_de(filtered, DeParams(lfc_shrink=False))
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

import numpy as np
import pandas as pd
import pytest

from cell_ledger.analysis import (
    DeParams,
    build_anndata,
    filter_genes,
    load_annotation,
    load_counts,
    lookup_genes,
    run_de,
    run_qc,
    score_markers,
)
from cell_ledger.report.models import MarkerExpectation


def test_load_counts_rejects_non_integer(tmp_path):
    p = tmp_path / "bad.tsv"
    pd.DataFrame({"GSM1": [1.5, 2.0]}, index=pd.Index(["1", "2"], name="GeneID")).to_csv(
        p, sep="\t"
    )
    with pytest.raises(ValueError, match="non-integer"):
        load_counts(p)


def test_reconciliation_reports_every_mismatch(synthetic, synthetic_files):
    counts = load_counts(synthetic_files[0])
    annotation = load_annotation(synthetic_files[1])
    adata, rec = build_anndata(counts, synthetic.sheet, annotation, synthetic.contrast)
    assert rec.contrast_gsms_missing_from_counts == ["GSM42"]
    assert rec.columns_not_in_sheet == ["GSM999"]
    assert rec.n_case == 4 and rec.n_control == 4
    assert adata.shape == (8, 1500)
    assert list(adata.obs["arm"]) == ["case"] * 4 + ["control"] * 4
    assert isinstance(adata.var, pd.DataFrame) and adata.var.loc["3", "Symbol"] == "XIST"
    assert adata.layers["counts"].dtype == np.int64


def test_qc_flags_low_depth_sex_mismatch_and_pca(synthetic, synthetic_files):
    counts = load_counts(synthetic_files[0])
    adata, _ = build_anndata(
        counts, synthetic.sheet, load_annotation(synthetic_files[1]), synthetic.contrast
    )
    qc = run_qc(adata)
    by = {s.gsm: s for s in qc.samples}
    assert "very_low_library_size" in by["GSM8"].flags or "low_library_size" in by["GSM8"].flags
    assert by["GSM8"].predicted_sex == "male" and by["GSM8"].reported_sex == "female"
    assert "sex_mismatch" in by["GSM8"].flags
    assert all("sex_mismatch" not in by[g].flags for g in ["GSM1", "GSM5"])
    assert qc.pca is not None and len(qc.pca.coords) == 8
    assert qc.pca.arm_r2_pc1 is not None
    # the low-depth sample is the PC1 outlier, as it should be
    pc1 = {g: c[0] for g, c in qc.pca.coords.items()}
    assert max(pc1, key=lambda g: abs(pc1[g])) == "GSM8"
    assert "sex_mismatches" in qc.flags
    assert all(s.pct_mito > 0 for s in qc.samples)


def test_filter_and_de_recover_planted_genes(synthetic, synthetic_files):
    counts = load_counts(synthetic_files[0])
    adata, _ = build_anndata(
        counts, synthetic.sheet, load_annotation(synthetic_files[1]), synthetic.contrast
    )
    filtered, fsum = filter_genes(adata, min_count=10)
    assert fsum.n_genes_after < fsum.n_genes_before
    assert "5" not in filtered.var_names  # silent gene removed
    results, normed, summary = run_de(filtered, DeParams(lfc_shrink=True))
    assert normed.shape == (8, filtered.n_vars)
    sig_up = set(results[(results.padj < 0.05) & (results.log2fc > 0)].index)
    sig_down = set(results[(results.padj < 0.05) & (results.log2fc < 0)].index)
    assert len(sig_up & set(synthetic.up)) >= 40
    assert len(sig_down & set(synthetic.down)) >= 40
    assert summary.summary.n_up == len(sig_up) and summary.summary.lfc_shrunk
    assert summary.top_up[0].symbol is not None
    assert "log2fc_unshrunk" in results.columns

    assert isinstance(adata.var, pd.DataFrame)
    rows = lookup_genes(
        ["G10", "G60", "SILENT", "NOPE", "3"],
        adata.var,
        results=results,
        normed=normed,
        arms=pd.Series(adata.obs["arm"].astype(str), index=adata.obs_names),
    )
    verdicts = {r.query: r.verdict for r in rows}
    assert verdicts == {
        "G10": "up",
        "G60": "down",
        "SILENT": "not_tested",
        "NOPE": "not_found",
        "3": "up",
    }
    g10 = next(r for r in rows if r.query == "G10")
    assert g10.mean_norm_case is not None and g10.mean_norm_control is not None
    assert g10.mean_norm_case > g10.mean_norm_control and g10.rank_by_padj is not None

    score = score_markers(
        [
            MarkerExpectation(symbol="G10", direction="up"),
            MarkerExpectation(symbol="G60", direction="up"),
            MarkerExpectation(symbol="NOPE", direction="down"),
        ],
        rows,
        top_n=200,
    )
    assert (score.n_expected, score.n_recovered_sig) == (3, 1)
    assert score.results[1].in_top_n_correct_sign is False


def test_de_requires_both_arms(synthetic, synthetic_files):
    counts = load_counts(synthetic_files[0])
    adata, _ = build_anndata(
        counts, synthetic.sheet, load_annotation(synthetic_files[1]), synthetic.contrast
    )
    only_case = adata[adata.obs["arm"] == "case"].copy()
    with pytest.raises(ValueError, match="case and control"):
        run_de(only_case, DeParams())


def test_sex_prediction_needs_clear_evidence():
    from cell_ledger.analysis.qc import _predict_sex

    assert _predict_sex(xist_cpm=300.0, y_cpm=0.0) == "female"
    assert _predict_sex(xist_cpm=30.0, y_cpm=80.0) == "male"
    assert _predict_sex(xist_cpm=40.0, y_cpm=1.5) is None  # both weak: no call, no flag
    assert _predict_sex(xist_cpm=0.0, y_cpm=0.0) is None

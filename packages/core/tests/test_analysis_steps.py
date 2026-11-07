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
    fit = run_de(filtered, DeParams(lfc_shrink=True))
    results, normed, summary, plan = fit.results, fit.normed, fit.summary, fit.plan
    assert plan.pairing == "none" and summary.summary.design == "~arm"
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


def test_blocked_design_when_pairing_is_complete(synthetic, synthetic_files):
    from cell_ledger.analysis.de import plan_design

    counts = load_counts(synthetic_files[0])
    adata, _ = build_anndata(
        counts, synthetic.sheet, load_annotation(synthetic_files[1]), synthetic.contrast
    )
    filtered, _ = filter_genes(adata, min_count=10)
    fit = run_de(filtered, DeParams(), blocking="donor")
    results, summary, plan = fit.results, fit.summary, fit.plan
    assert plan.pairing == "modelled" and plan.dropped == []
    assert summary.summary.design == "~block + arm" and summary.summary.blocking == "donor"
    sig_up = set(results[(results.padj < 0.05) & (results.log2fc > 0)].index)
    assert len(sig_up & set(synthetic.up)) >= 40

    # moving one case to a new donor leaves it AND its former partner unpaired: both dropped
    obs = adata.obs
    assert isinstance(obs, pd.DataFrame)
    obs.loc["GSM1", "donor"] = "lonely"
    plan = plan_design(obs, "donor", min_per_group=3)
    assert plan.pairing == "incomplete_dropped" and plan.dropped == ["GSM1", "GSM5"]
    # too few complete pairs -> pairing ignored with a warning, all samples kept
    obs.loc[["GSM2", "GSM3"], "donor"] = ["x", "y"]
    plan = plan_design(obs, "donor", min_per_group=3)
    assert plan.pairing == "ignored" and len(plan.kept) == 8 and plan.warnings


def test_lookup_distinguishes_untestable_from_no_evidence():
    var = pd.DataFrame({"Symbol": ["A", "B", "C"]}, index=pd.Index(["1", "2", "3"], name="gene_id"))
    results = pd.DataFrame(
        {
            "symbol": ["A", "B", "C"],
            "base_mean": [10.0, 0.5, 100.0],
            "log2fc": [0.1, 2.0, 1.0],
            "pvalue": [0.6, 0.01, np.nan],
            "padj": [0.9, np.nan, np.nan],
        },
        index=pd.Index(["1", "2", "3"], name="gene_id"),
    )
    rows = lookup_genes(["A", "B", "C"], var, results=results, normed=None, arms=None)
    assert [(r.verdict, r.reason) for r in rows] == [
        ("no_evidence", None),
        ("untestable", "independent_filtering"),
        ("untestable", "outlier_or_all_zero"),
    ]


def test_filter_keeps_genes_of_interest_with_any_reads():
    import anndata as ad

    # 6 samples, 3 per arm. Gene "1" passes; "3605" (IL17A) is low but present; "9" is silent.
    counts = np.array(
        [[50, 2, 0], [60, 0, 0], [55, 3, 0], [40, 1, 0], [45, 0, 0], [52, 4, 0]], dtype=np.int64
    )
    obs = pd.DataFrame({"arm": ["case"] * 3 + ["control"] * 3}, index=[f"GSM{i}" for i in range(6)])
    adata = ad.AnnData(X=counts.astype(float), obs=obs, var=pd.DataFrame(index=["1", "3605", "9"]))
    adata.layers["counts"] = counts

    plain, fsum = filter_genes(adata, min_count=10)
    assert list(plain.var_names) == ["1"] and fsum.kept_below_threshold == []

    asked, fsum = filter_genes(adata, min_count=10, always_keep=["3605", "9"])
    # The asked-for low gene is tested; a gene with no reads at all still is not.
    assert list(asked.var_names) == ["1", "3605"]
    assert fsum.kept_below_threshold == ["3605"] and fsum.n_genes_after == 2

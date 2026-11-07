"""Design eligibility in the per-dataset fit: repeated samples per block and arm are
summed into one observation, unmodelled donor repeats are called out, and the fitted
membership is recorded."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd

from cell_ledger.analysis import DeParams, PipelineParams, run_de, run_pipeline
from cell_ledger.analysis.bundle import build_anndata
from cell_ledger.analysis.de import plan_design
from cell_ledger.analysis.filtering import filter_genes
from cell_ledger.samplesheet import Contrast, SampleSheet


def _with_donors(syn, donors: dict[str, str], blocking: str | None):  # type: ignore[no-untyped-def]
    samples = [
        s.model_copy(update={"donor": donors.get(s.gsm, s.donor)}) for s in syn.sheet.samples
    ]
    sheet = SampleSheet(gse=syn.sheet.gse, assay=syn.sheet.assay, title="syn", samples=samples)
    contrast = Contrast(**{**syn.contrast.model_dump(), "blocking": blocking})
    return sheet, contrast


def test_plan_collapses_repeated_samples_per_block_and_arm() -> None:
    obs = pd.DataFrame(
        {
            "arm": ["case", "case", "case", "control", "case", "control", "case", "control"],
            "donor": ["p1", "p1", "p1", "p1", "p2", "p2", "p3", "p3"],
        },
        index=[f"GSM{i}" for i in range(1, 9)],
    )
    plan = plan_design(obs, "donor", min_per_group=3)
    assert plan.design == "~block + arm" and plan.pairing == "modelled"
    assert plan.collapsed == {"p1|case": ["GSM1", "GSM2", "GSM3"]}
    units = plan.units
    assert len(units) == 6 and units["p1|case"] == ["GSM1", "GSM2", "GSM3"]
    assert any("summed into 1 observations" in w for w in plan.warnings)


def test_plan_flags_donor_repeats_without_blocking() -> None:
    obs = pd.DataFrame(
        {
            "arm": ["case", "case", "control", "control", "case", "control"],
            "donor": ["p1", "p1", "p2", "p3", "p4", "p5"],
        },
        index=[f"GSM{i}" for i in range(1, 7)],
    )
    plan = plan_design(obs, None, min_per_group=3)
    assert plan.design == "~arm" and plan.collapsed == {}
    assert plan.unmodelled_dependence and "repeat a donor" in plan.unmodelled_dependence


def test_run_de_sums_counts_before_fitting(synthetic) -> None:  # type: ignore[no-untyped-def]
    # cases GSM1..4 come from donors d1..d4 paired with controls GSM5..8; make GSM2 a
    # second biopsy of d1 so block d1 has two case samples
    sheet, contrast = _with_donors(synthetic, {"GSM2": "d1", "GSM6": "d2"}, "donor")
    # d2 now has control GSM6 only (its case GSM2 moved to d1): drop it as unpaired
    adata, _ = build_anndata(synthetic.counts, sheet, synthetic.annotation, contrast)
    filtered, _ = filter_genes(adata)
    fit = run_de(filtered, DeParams(lfc_shrink=False), blocking="donor")
    s = fit.summary.summary
    assert s.collapsed == {"d1|case": ["GSM1", "GSM2"]}
    assert s.n_samples_collapsed == 2
    assert s.dropped_unpaired == ["GSM6"]
    assert set(s.gsms_fitted) == {"GSM1", "GSM2", "GSM3", "GSM4", "GSM5", "GSM7", "GSM8"}
    assert s.n_case_used == 3 and s.n_control_used == 3  # d1 (collapsed), d3, d4
    assert list(fit.normed.index) == list(fit.arms.index)
    assert "d1|case" in fit.normed.index
    # the collapsed observation holds the sum of its two samples' counts
    summed = synthetic.counts.loc[filtered.var_names, ["GSM1", "GSM2"]].sum(axis=1)
    assert np.allclose(fit.normed.loc["d1|case"].to_numpy() > 0, summed.to_numpy() > 0)
    # planted genes that survived the count filter still come out, with the right sign
    res = fit.results
    up = [g for g in synthetic.up if g in res.index]
    down = [g for g in synthetic.down if g in res.index]
    assert len(up) >= 30 and len(down) >= 30
    assert (res.loc[up, "log2fc"] > 0).mean() > 0.95
    assert (res.loc[down, "log2fc"] < 0).mean() > 0.95


def test_pipeline_reports_collapse_as_a_qualification(
    synthetic, synthetic_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    sheet, contrast = _with_donors(synthetic, {"GSM2": "d1", "GSM6": "d2"}, "donor")
    report = run_pipeline(
        counts_path=synthetic_files[0],
        annotation_path=synthetic_files[1],
        sheet=sheet,
        contrast=contrast,
        out_dir=tmp_path / "collapsed",
        params=PipelineParams(run_enrichment=False, figures=False, genes_of_interest=["G10"]),
    )
    assert report.status == "complete" and report.de is not None
    assert any("summed into 1 observations" in q for q in report.qualifications)
    assert report.de.summary.n_samples_collapsed == 2
    assert report.gene_lookup[0].verdict == "up"
    normed = pd.read_csv(tmp_path / "collapsed" / "normalized_counts.tsv", sep="\t", index_col=0)
    assert "d1|case" in normed.columns and "GSM1" not in normed.columns


def test_pipeline_qualifies_unmodelled_dependence(
    synthetic, synthetic_files, tmp_path: Path
) -> None:  # type: ignore[no-untyped-def]
    sheet, contrast = _with_donors(synthetic, {"GSM2": "d1"}, None)
    report = run_pipeline(
        counts_path=synthetic_files[0],
        annotation_path=synthetic_files[1],
        sheet=sheet,
        contrast=contrast,
        out_dir=tmp_path / "dep",
        params=PipelineParams(run_enrichment=False, figures=False),
    )
    assert report.status == "complete"
    assert any("repeat a donor within an arm" in q for q in report.qualifications)
    assert report.de is not None and report.de.summary.collapsed == {}

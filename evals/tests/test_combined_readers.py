"""Compatibility with outputs from an explicitly selected, unchanged main checkout."""

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import anndata as ad
import pandas as pd
import pytest

from evals.readers import read_analysis

PRODUCE = """
import json, runpy, sys
from pathlib import Path
from cell_ledger.analysis import PipelineParams, run_pipeline
checkout, out = map(Path, sys.argv[1:])
syn = runpy.run_path(str(checkout / "packages/core/tests/conftest.py"))["make_synthetic"]()
counts, annot = out / "source.tsv.gz", out / "annotation.tsv.gz"
syn.counts.to_csv(counts, sep="\\t")
syn.annotation.to_csv(annot, sep="\\t")
for mode in ["combined", "singleton", "multiple"]:
    sheet = syn.sheet.model_copy(deep=True)
    contrast = syn.contrast.model_copy(deep=True)
    contrast.name, contrast.blocking = mode, "donor"
    if mode != "singleton":
        sheet.by_gsm("GSM2").donor = "d1"
    if mode == "multiple":
        sheet.by_gsm("GSM6").donor = "d1"
    report = run_pipeline(counts_path=counts, annotation_path=annot,
        sheet=sheet, contrast=contrast, out_dir=out / mode,
        params=PipelineParams(run_enrichment=False, figures=False, lfc_shrink=False, n_cpus=1))
    assert report.status == "complete", report.error
    assert report.de is not None
    if mode != "singleton":
        assert report.de.summary.collapsed
    (out / (mode + "-design.json")).write_text(sheet.model_dump_json())
"""


def fingerprints(folder):
    return {
        str(p.relative_to(folder)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in folder.rglob("*")
        if p.is_file()
    }


@pytest.fixture(scope="module")
def latest_outputs(tmp_path_factory):
    configured = os.environ.get("CELL_LEDGER_SHARED_CHECKOUT")
    if not configured:
        pytest.skip("Set CELL_LEDGER_SHARED_CHECKOUT to test unchanged latest-main producer")
    checkout = Path(configured).resolve()
    out = tmp_path_factory.mktemp("latest-combined-readers")
    env = {
        **os.environ,
        "PYTHONPATH": str(checkout / "packages/core/src"),
        "PYTHONDONTWRITEBYTECODE": "1",
        "MPLCONFIGDIR": str(out / "mpl"),
    }
    proc = subprocess.run(
        [sys.executable, "-c", PRODUCE, str(checkout), str(out)],
        cwd=checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out


@pytest.mark.parametrize("mode", ["combined", "singleton", "multiple"])
def test_actual_latest_producer(latest_outputs, mode):
    folder = latest_outputs / mode
    before = fingerprints(folder)
    result = read_analysis(folder, source_counts=latest_outputs / "source.tsv.gz")
    assert not result.errors, result.errors
    assert result.checks["normalized_counts"] == "passed"
    assert result.checks["source_counts"] == "passed"
    if mode != "singleton":
        assert result.checks["combined_observations"] == "passed"
        assert any("no independent fitted matrix" in s for s in result.unavailable)
        assert result.result()["consistent"] is None
        assert "normed_counts" not in ad.read_h5ad(folder / "dataset.h5ad").layers
    assert result.result()["scientific_score"] is None
    assert fingerprints(folder) == before


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "unknown",
        "dropped",
        "collision",
        "fitted",
        "count",
        "arm_total",
        "cross_arm",
        "cross_donor",
        "embedded",
        "columns",
        "negative",
        "nan",
    ],
)
def test_corrupt_combined_output(latest_outputs, tmp_path, change):
    folder = tmp_path / "copy"
    shutil.copytree(latest_outputs / "combined", folder)
    path = folder / "report.json"
    doc = json.loads(path.read_text())
    summary = doc["de"]["summary"]
    mapping = summary["collapsed"]
    unit = next(iter(mapping))
    if change == "duplicate":
        mapping[unit].append(mapping[unit][0])
    elif change == "unknown":
        mapping[unit][1] = "GSM404"
    elif change == "dropped":
        mapping[unit][1] = summary["dropped_unpaired"][0]
    elif change == "collision":
        mapping[summary["gsms_fitted"][0]] = mapping.pop(unit)
    elif change == "fitted":
        summary["gsms_fitted"].pop()
    elif change == "count":
        summary["n_samples_collapsed"] += 1
    elif change == "arm_total":
        summary["n_case_used"] += 1
    elif change in {"cross_arm", "cross_donor"}:
        mapping[unit][1] = "GSM5" if change == "cross_arm" else "GSM3"
    elif change == "embedded":
        pass
    else:
        table = pd.read_csv(folder / "normalized_counts.tsv", sep="\t", index_col=0)
        if change == "columns":
            table = table.rename(columns={unit: "invented"})
        else:
            table.iloc[0, 0] = -1 if change == "negative" else float("nan")
        table.to_csv(folder / "normalized_counts.tsv", sep="\t")
    path.write_text(json.dumps(doc))
    # Align both claimed mappings so most tests exercise membership checks,
    # not merely detection of two disagreeing copies of the same claim.
    data = ad.read_h5ad(folder / "dataset.h5ad")
    data.uns["collapsed"] = json.dumps({} if change == "embedded" else mapping)
    data.write_h5ad(folder / "dataset.h5ad")
    result = read_analysis(folder, source_counts=latest_outputs / "source.tsv.gz")
    assert result.errors, change
    assert result.result()["consistent"] is False


def test_positive_normalized_change_is_explicitly_unverified(latest_outputs, tmp_path):
    folder = tmp_path / "copy"
    shutil.copytree(latest_outputs / "combined", folder)
    table = pd.read_csv(folder / "normalized_counts.tsv", sep="\t", index_col=0)
    table.iloc[0, 0] += 1
    table.to_csv(folder / "normalized_counts.tsv", sep="\t")
    result = read_analysis(folder, source_counts=latest_outputs / "source.tsv.gz")
    assert not result.errors
    assert any("no independent fitted matrix" in s for s in result.unavailable)
    assert result.result()["consistent"] is None

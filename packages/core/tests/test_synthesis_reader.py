"""Read unchanged current-main producer outputs; these are synthetic integrity checks."""

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pandas as pd
import pytest

from packages.core.tests.readers import read_comparison

PRODUCE = """
import json, runpy, sys
from pathlib import Path
from cell_ledger.analysis import PipelineParams, run_pipeline
from cell_ledger.compare import CompareParams, run_comparison
checkout, out = map(Path, sys.argv[1:])
make = runpy.run_path(str(checkout / 'packages/core/tests/conftest.py'))['make_synthetic']
folders = []
for number in (11, 12, 13):
    syn = make(seed=number)
    name = f'GSE{number}'
    def rename(gsm): return f'GSM{number * 1000 + int(gsm[3:])}'
    counts = syn.counts.rename(columns=rename)
    sheet = syn.sheet.model_copy(deep=True)
    sheet.gse = name
    for sample in sheet.samples: sample.gsm = rename(sample.gsm)
    contrast = syn.contrast.model_copy(deep=True)
    contrast.gse = name
    contrast.case_gsms = [rename(g) for g in contrast.case_gsms]
    contrast.control_gsms = [rename(g) for g in contrast.control_gsms]
    counts_path, annotation = out / f'{name}.tsv.gz', out / f'{name}-annotation.tsv.gz'
    counts.to_csv(counts_path, sep='\\t')
    syn.annotation.to_csv(annotation, sep='\\t')
    folder = out / name
    report = run_pipeline(counts_path=counts_path, annotation_path=annotation,
        sheet=sheet, contrast=contrast, out_dir=folder,
        params=PipelineParams(run_enrichment=False, figures=False, lfc_shrink=False, n_cpus=1))
    assert report.status == 'complete', report.error
    folders.append(folder)
modes = [('complete', folders), ('two', folders[:2]),
    ('insufficient', folders[:1]), ('missing', [out / 'absent'])]
for mode, members in modes:
    report = run_comparison(members, out / mode, name='synthetic', question='fixture',
        case_label='case', control_label='control',
        params=CompareParams(figures=mode=='complete', pooled_enrichment=False))
    expected = 'complete' if mode in ['complete','two'] else 'insufficient'
    assert report.status == expected, report.error
(out / 'source-map.json').write_text(json.dumps({
    json.loads((p/'report.json').read_text())['gse'] + ':'
    + json.loads((p/'report.json').read_text())['contrast']['name']: str(p)
    for p in folders
}))
"""


@pytest.fixture(scope="module")
def comparison_outputs(tmp_path_factory):
    configured = os.environ.get("CELL_LEDGER_SHARED_CHECKOUT")
    if not configured:
        pytest.skip("Set CELL_LEDGER_SHARED_CHECKOUT to test unchanged shared producer")
    checkout = Path(configured).resolve()
    out = tmp_path_factory.mktemp("comparison-reader-producer")
    proc = subprocess.run(
        [sys.executable, "-c", PRODUCE, str(checkout), str(out)],
        cwd=checkout,
        env={
            **os.environ,
            "PYTHONPATH": str(checkout / "packages/core/src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MPLCONFIGDIR": str(out / "mpl"),
        },
        capture_output=True,
        text=True,
        timeout=120,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out, json.loads((out / "source-map.json").read_text())


@pytest.mark.parametrize("mode", ["complete", "two", "insufficient", "missing"])
def test_current_main_reports_are_read_without_scientific_scores(comparison_outputs, mode):
    out, sources = comparison_outputs
    folder = out / mode
    before = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    result = read_comparison(folder, source_runs=sources)
    assert not result.errors, result.errors
    assert result.source == json.loads((folder / "comparison.json").read_text())
    assert result.result()["scientific_score"] is None
    assert result.unavailable  # No independent numerical/domain reference supplied.
    assert before == {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    if mode == "two":
        assert result.source["effective_min_studies"] == 2 and result.source["warnings"]
    if mode == "complete":
        assert "concordance" in result.checks and result.checks["concordance"] == "passed"
        assert "figures:concordance" in result.checks  # File/figure roles must not collide.


@pytest.mark.parametrize(
    "change",
    [
        "duplicate",
        "membership",
        "denominator",
        "concordance",
        "sensitivity",
        "missing_file",
        "path",
    ],
)
def test_corrupt_comparison_outputs_are_detected(comparison_outputs, tmp_path, change):
    out, sources = comparison_outputs
    folder = tmp_path / "comparison"
    shutil.copytree(out / "complete", folder)
    path = folder / "comparison.json"
    doc = json.loads(path.read_text())
    if change == "duplicate":
        doc["members"].append(doc["members"][0])
    elif change == "membership":
        doc["members"][0]["pooled"] = False
    elif change == "denominator":
        table_path = folder / doc["files"]["gene_table"]
        table = pd.read_csv(table_path, sep="\t", index_col=0)
        table.iloc[0, table.columns.get_loc("n_tested")] = 100
        table.to_csv(table_path, sep="\t")
    elif change == "concordance":
        doc["concordance"]["members"][0] = "invented"
    elif change == "sensitivity":
        doc["leave_one_out"].pop()
    elif change == "missing_file":
        (folder / doc["files"]["gene_table"]).unlink()
    else:
        doc["files"]["members"] = "../outside.tsv"
    path.write_text(json.dumps(doc))
    assert read_comparison(folder, source_runs=sources).errors


def test_failed_comparison_is_a_recorded_outcome_not_parser_failure(tmp_path):
    report = {
        "name": "failed",
        "status": "failed",
        "error": "test failure",
        "members": [],
        "excluded": [],
        "warnings": [],
        "questions": [],
        "sensitivity": [],
        "leave_one_out": [],
        "files": {},
    }
    (tmp_path / "comparison.json").write_text(json.dumps(report))
    result = read_comparison(tmp_path)
    assert not result.errors and result.source["status"] == "failed"
    assert result.result()["consistent"] is None


def test_report_cannot_direct_reader_to_unapproved_source_paths(comparison_outputs):
    out, _ = comparison_outputs
    result = read_comparison(out / "complete")
    assert any("source reports not supplied" in reason for reason in result.unavailable)
    assert not any(name.startswith("source:") for name in result.sha256)

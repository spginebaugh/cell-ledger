"""Inspect actual shared-producer outputs; mutate only temporary test artifacts."""

import gzip
import hashlib
import json
import shutil
import subprocess
import sys

import httpx
import pandas as pd
import pytest

from cell_ledger.analysis import PipelineParams, run_pipeline
from cell_ledger.geo.fetch import counts_url, fetch_series, soft_url
from evals.readers import read_analysis, read_collection
from packages.core.tests.conftest import make_synthetic


def fingerprints(root):
    return {
        str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in root.rglob("*")
        if p.is_file()
    }


async def collect(root, *, absent=False, fractional=False):
    soft = "^SERIES = GSE1\n"
    for i in range(1, 4):
        soft += (
            f"^SAMPLE = GSM{i}\n!Sample_title = sample {i}\n"
            "!Sample_organism_ch1 = Homo sapiens\n"
            "!Sample_library_strategy = RNA-Seq\n"
            "!Sample_characteristics_ch1 = treatment: example\n"
        )
    counts = f"GeneID\tGSM1\tGSM2\n001\t{1.5 if fractional else 10}\t20\n002\t30\t40\n"
    files = {
        counts_url("GSE1"): gzip.compress(counts.encode()),
        soft_url("GSE1"): gzip.compress(soft.encode()),
    }

    def respond(request):
        return (
            httpx.Response(200, content=files[str(request.url)])
            if not absent and str(request.url) in files
            else httpx.Response(404)
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
        await fetch_series(client, "GSE1", root)
    return root / "GSE1"


@pytest.mark.parametrize("fractional", [False, True])
async def test_collection_real_producer_and_read_only(tmp_path, fractional):
    folder = await collect(tmp_path, fractional=fractional)
    before = fingerprints(folder)
    result = read_collection(folder)
    assert not result.errors, result.errors
    assert result.result()["consistent"] is True
    assert result.result()["scientific_score"] is None
    assert result.source["samples"][2]["exclusions"] == ["not_in_counts"]
    assert result.source["status"] == ("excluded" if fractional else "ready")
    assert fingerprints(folder) == before


async def test_collection_without_counts_is_not_a_reader_failure(tmp_path):
    folder = await collect(tmp_path, absent=True)
    result = read_collection(folder)
    assert not result.errors
    assert result.source["exclusions"] == ["no_ncbi_counts"]
    assert result.result()["consistent"] is None
    assert result.unavailable


@pytest.mark.parametrize(
    "change", ["hash", "coverage", "duplicate", "metadata", "traversal", "symlink"]
)
async def test_collection_detects_corruption(tmp_path, change):
    folder = await collect(tmp_path)
    path = folder / "dataset.json"
    doc = json.loads(path.read_text())
    if change == "hash":
        (folder / doc["files"]["counts"]["name"]).write_bytes(b"corrupt")
    elif change == "coverage":
        doc["samples"][0]["in_counts"] = False
    elif change == "duplicate":
        doc["samples"].append(doc["samples"][0])
    elif change == "metadata":
        doc["samples"][0]["title"] = "invented"
    elif change == "traversal":
        doc["files"]["counts"]["name"] = "../secret"
    else:
        original = folder / doc["files"]["counts"]["name"]
        target = tmp_path / "outside.gz"
        original.rename(target)
        original.symlink_to(target)
    path.write_text(json.dumps(doc))
    before = fingerprints(folder)
    result = read_collection(folder)
    assert result.errors
    assert result.result()["consistent"] is False
    assert fingerprints(folder) == before


@pytest.fixture(scope="module")
def analysis_outputs(tmp_path_factory):
    root = tmp_path_factory.mktemp("shared-analysis-readers")
    fixture = make_synthetic()
    counts = root / "source.tsv.gz"
    annotation = root / "annotation.tsv.gz"
    fixture.counts.to_csv(counts, sep="\t")
    fixture.annotation.to_csv(annotation, sep="\t")
    outputs = {}
    for mode in ["complete", "paired", "qc_only", "blocked", "error", "empty_filter"]:
        contrast = fixture.contrast.model_copy(deep=True)
        contrast.name = mode
        if mode == "paired":
            contrast.blocking = "donor"
            contrast.control_gsms = contrast.control_gsms[:3]
        elif mode == "qc_only":
            contrast.case_gsms = ["GSM1", "GSM2", "GSM42"]
        elif mode == "blocked":
            contrast.case_gsms = ["GSM1", "GSM2"]
        folder = root / mode
        report = run_pipeline(
            counts_path=counts if mode != "error" else root / "missing.gz",
            annotation_path=annotation,
            sheet=fixture.sheet,
            contrast=contrast,
            out_dir=folder,
            params=PipelineParams(
                run_enrichment=False,
                figures=False,
                lfc_shrink=False,
                n_cpus=1,
                min_count=10**9 if mode == "empty_filter" else 10,
            ),
        )
        assert report.status == (
            "complete"
            if mode in ["complete", "paired"]
            else "qc_only"
            if mode in ["qc_only", "empty_filter"]
            else "blocked"
        )
        outputs[mode] = folder
    return outputs, counts


@pytest.mark.parametrize(
    "mode", ["complete", "paired", "qc_only", "blocked", "error", "empty_filter"]
)
def test_analysis_real_producer_modes(analysis_outputs, mode):
    outputs, counts = analysis_outputs
    folder = outputs[mode]
    before = fingerprints(folder)
    result = read_analysis(folder, source_counts=counts)
    assert not result.errors, result.errors
    assert result.identity == {"gse": "GSE1", "contrast": mode}
    assert result.source == json.loads((folder / "report.json").read_text())
    assert result.result()["scientific_score"] is None
    assert result.unavailable  # CSV cannot restore per-field evidence.
    if mode == "paired":
        assert result.source["de"]["summary"]["dropped_unpaired"]
    if mode == "error":
        assert result.source["error"] and "anndata" not in result.checks
    assert fingerprints(folder) == before


@pytest.mark.parametrize(
    "change",
    [
        "raw_values",
        "groups",
        "sample_drop",
        "gene_id",
        "missing_file",
        "unsafe_path",
        "source_values",
    ],
)
def test_analysis_detects_corruption(analysis_outputs, tmp_path, change):
    outputs, counts = analysis_outputs
    folder = tmp_path / "analysis"
    shutil.copytree(outputs["complete"], folder)
    source = tmp_path / "source.gz"
    shutil.copy2(counts, source)
    path = folder / "report.json"
    doc = json.loads(path.read_text())
    # The pipeline exports counts.tsv and samples.csv (no AnnData file), so corruption is
    # applied to those tables.
    if change in ["raw_values", "gene_id"]:
        table = pd.read_csv(folder / "counts.tsv", sep="\t", index_col=0)
        if change == "raw_values":
            table.iloc[0, 0] += 1
        else:
            table.index = ["invented", *table.index[1:]]
        table.to_csv(folder / "counts.tsv", sep="\t")
    elif change in ["groups", "sample_drop"]:
        table = pd.read_csv(folder / "samples.csv", index_col=0)
        if change == "groups":
            table["arm"] = "invented"
        else:
            table = table.iloc[1:]
        table.to_csv(folder / "samples.csv")
    elif change == "missing_file":
        (folder / "counts.tsv").unlink()
    elif change == "unsafe_path":
        doc["files"]["counts"] = "../source.gz"
        path.write_text(json.dumps(doc))
    else:
        text = gzip.decompress(source.read_bytes()).decode()
        rows = text.splitlines()
        row = rows[1].split("\t")
        row[1] = str(int(row[1]) + 1)
        rows[1] = "\t".join(row)
        source.write_bytes(gzip.compress(("\n".join(rows) + "\n").encode()))
    assert read_analysis(folder, source_counts=source).errors


def test_multiple_contrasts_and_missing_source(analysis_outputs):
    outputs, _ = analysis_outputs
    results = [read_analysis(outputs[name]) for name in ["complete", "paired"]]
    assert results[0].identity != results[1].identity
    assert all(any("not supplied" in reason for reason in r.unavailable) for r in results)


@pytest.mark.parametrize("kind", ["collection", "analysis"])
def test_malformed_json_is_reported(tmp_path, kind):
    (tmp_path / ("dataset.json" if kind == "collection" else "report.json")).write_text("[]")
    result = read_collection(tmp_path) if kind == "collection" else read_analysis(tmp_path)
    assert result.errors


async def test_cli_emits_json_without_modifying_inputs(tmp_path):
    folder = await collect(tmp_path)
    before = fingerprints(folder)
    proc = subprocess.run(
        [sys.executable, "-m", "evals.readers", "collection", str(folder)],
        capture_output=True,
        text=True,
        check=True,
    )
    assert json.loads(proc.stdout)["consistent"] is True
    assert fingerprints(folder) == before


async def test_collection_wrong_study_even_when_file_hash_matches(tmp_path):
    folder = await collect(tmp_path)
    path = folder / "dataset.json"
    doc = json.loads(path.read_text())
    soft = folder / doc["files"]["soft"]["name"]
    soft.write_bytes(gzip.compress(gzip.decompress(soft.read_bytes()).replace(b"GSE1", b"GSE2")))
    doc["files"]["soft"]["md5"] = hashlib.md5(soft.read_bytes()).hexdigest()
    doc["files"]["soft"]["bytes"] = soft.stat().st_size
    path.write_text(json.dumps(doc))
    result = read_collection(folder)
    assert result.checks["file:soft"] == "passed"
    assert any("SOFT series accession differs" in error for error in result.errors)


@pytest.mark.parametrize("extra", ["duplicate", "unknown"])
def test_invalid_dropped_sample_report(analysis_outputs, tmp_path, extra):
    outputs, counts = analysis_outputs
    folder = tmp_path / "paired"
    shutil.copytree(outputs["paired"], folder)
    path = folder / "report.json"
    doc = json.loads(path.read_text())
    dropped = doc["de"]["summary"]["dropped_unpaired"]
    dropped.append(dropped[0] if extra == "duplicate" else "GSM404")
    path.write_text(json.dumps(doc))
    result = read_analysis(folder, source_counts=counts)
    assert any("Invalid dropped-sample identities" in error for error in result.errors)


@pytest.mark.parametrize("kind", ["collection", "analysis"])
def test_malformed_record_fields_are_reported(tmp_path, kind):
    filename = "dataset.json" if kind == "collection" else "report.json"
    (tmp_path / filename).write_text(json.dumps({"gse": "GSE1", "status": "ready", "files": []}))
    result = read_collection(tmp_path) if kind == "collection" else read_analysis(tmp_path)
    assert (
        result.errors
        and result.checks[f"{'dataset_record' if kind == 'collection' else 'analysis_report'}"]
        == "failed"
    )

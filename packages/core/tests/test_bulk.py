import gzip
import json
from pathlib import Path

import anndata as ad
import numpy as np
import pandas as pd
import pytest

from cell_ledger.bulk import Label, harmonize_rules, parse_matrix, qc_dataset, validate_labels
from cell_ledger.bundle import assemble_dataset, load_bundle
from cell_ledger.geo.models import GeoError, GeoSample, GeoSeries


@pytest.fixture
def study():
    samples = [
        GeoSample(
            gsm=f"GSM{i + 1}",
            fields={
                "title": [f"sample {i}"],
                "platform_id": ["GPL1"],
                "organism_ch1": ["Homo sapiens"],
                "library_strategy": ["RNA-Seq"],
                "characteristics_ch1": [
                    f"condition: {'treated' if i < 3 else 'untreated'}",
                    f"donor: {i}",
                ],
            },
        )
        for i in range(6)
    ]
    series = GeoSeries(
        gse="GSE1",
        samples=samples,
        source_url="https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE1",
    )
    rng = np.random.default_rng(42)
    matrix = pd.DataFrame(
        rng.poisson(15000, (100, 6)),
        index=[str(i) for i in range(100)],
        columns=[s.gsm for s in samples],
    )
    labels = [harmonize_rules(s, case="treated", control="untreated") for s in samples]
    return series, matrix, labels


def test_exact_evidence_and_confidence_required(study):
    sample = study[0].samples[0]
    for evidence, confidence in (("condition: imagined", 1), ("condition: treated", 0.6)):
        result = validate_labels(
            sample,
            {
                "group": Label(
                    value="case",
                    evidence=evidence,
                    source_field="characteristics_ch1",
                    confidence=confidence,
                )
            },
        )
        assert result.group == "unknown"
        assert result.needs_review
    assert harmonize_rules(sample).group == "unknown"


@pytest.mark.parametrize(
    "payload",
    [
        b"gene\tGSM1\tGSM1\na\t1\t2",
        b"gene\tGSM1\na\t-1",
        b"gene\tGSM1\na\tNaN",
        b"gene\tGSM1\na\tinf",
        b"gene\tGSM1\na\t1\na\t2",
        b"<html>error</html>",
    ],
)
def test_invalid_matrix_rejected(payload):
    with pytest.raises(GeoError):
        parse_matrix(payload)


def test_gzip_expansion_cap():
    with pytest.raises(GeoError, match="Expanded matrix"):
        parse_matrix(gzip.compress(b"gene\tGSM1\na\t1\n"), max_bytes=4)


def test_metadata_order_never_changes_sample_identity(study, tmp_path: Path):
    series, matrix, labels = study
    series.samples.reverse()
    labels.reverse()
    aligned, validation = qc_dataset(series, matrix, labels, units="counts")
    assert validation.de_ready
    assemble_dataset(tmp_path, series, aligned, labels, validation, {"url": "fixture"})
    counts, metadata, genes, info = load_bundle(tmp_path / "datasets/GSE1")
    assert metadata.loc["GSM1", "group"] == "case"
    assert metadata.loc["GSM6", "group"] == "control"
    assert list(counts.index) == list(matrix.columns)
    dataset = ad.read_h5ad(tmp_path / "datasets/GSE1/dataset.h5ad")
    np.testing.assert_array_equal(dataset.X, matrix.T.to_numpy())
    assert dataset.obs_names.tolist() == list(matrix.columns)
    assert not info["analysis_executed"]
    assert len(genes) == 100


@pytest.mark.parametrize("units", ["tpm", "unknown", "normalized"])
def test_integer_normalized_values_never_become_counts(study, units):
    series, matrix, labels = study
    _, result = qc_dataset(series, matrix, labels, units=units)
    assert not result.de_ready
    assert not result.library_sizes


def test_unmatched_and_missing_samples_block_de(study):
    series, matrix, labels = study
    matrix = matrix.rename(columns={"GSM1": "unrecorded sample name"})
    aligned, result = qc_dataset(series, matrix, labels, units="counts")
    assert "unrecorded sample name" not in aligned
    assert result.missing_samples == ["GSM1"]
    assert result.excluded_samples["unrecorded sample name"]
    assert not result.de_ready


@pytest.mark.parametrize("trap", ["mouse", "single-cell", "paired", "confounded", "duplicate"])
def test_unsafe_designs_blocked(study, trap):
    series, matrix, labels = study
    if trap == "mouse":
        series.samples[0].fields["organism_ch1"] = ["Mus musculus"]
    elif trap == "single-cell":
        series.samples[0].fields["library_source"] = ["transcriptomic single cell"]
    elif trap == "paired":
        labels[1].labels["donor"] = labels[0].labels["donor"]
    elif trap == "confounded":
        for sample in labels:
            sample.platform = "GPL1" if sample.group == "case" else "GPL2"
    elif trap == "duplicate":
        matrix["GSM2"] = matrix["GSM1"]
    _, result = qc_dataset(series, matrix, labels, units="counts")
    assert not result.de_ready
    assert result.issues


def test_assembler_rejects_uncached_accessions(study, tmp_path):
    series, matrix, labels = study
    _, validation = qc_dataset(series, matrix, labels, units="counts")
    matrix = matrix.rename(columns={"GSM1": "GSM999999"})
    with pytest.raises(GeoError, match="absent from fetched metadata"):
        assemble_dataset(tmp_path, series, matrix, labels, validation, {})


def test_low_confidence_not_exported_as_case(study):
    source = study[0].samples[0]
    result = validate_labels(
        source,
        {
            "group": Label(
                value="case",
                evidence="condition: treated",
                source_field="characteristics_ch1",
                confidence=0.2,
            )
        },
    )
    assert json.loads(result.model_dump_json())["group"] == "unknown"

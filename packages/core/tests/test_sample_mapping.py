import pandas as pd
import pytest

from cell_ledger.bulk import map_sample_columns
from cell_ledger.geo.models import GeoError, GeoSample, GeoSeries


def series(titles, descriptions=None):
    return GeoSeries(
        gse="GSE1",
        source_url="https://example.org",
        samples=[
            GeoSample(
                gsm=f"GSM{i + 1}",
                fields={"title": [title], "description": (descriptions or [[] for _ in titles])[i]},
            )
            for i, title in enumerate(titles)
        ],
    )


def test_documented_aliases_reorder_without_position_guesses():
    source = series(["first", "second"], [["Library name: A"], ["Column name in counts.tsv: B"]])
    matrix = pd.DataFrame({"B": [20], "A": [10]}, index=["gene1"])
    mapped, proof = map_sample_columns(source, matrix)
    assert list(mapped.columns) == ["GSM2", "GSM1"]
    assert mapped.loc["gene1", "GSM1"] == 10
    assert proof["B"]["evidence"] == "Column name in counts.tsv: B"


def test_prefix_mapping_requires_complete_unique_cohort():
    source = series(["RNAseq_A", "RNAseq_B"])
    mapped, proof = map_sample_columns(source, pd.DataFrame({"B": [2], "A": [1]}))
    assert list(mapped.columns) == ["GSM2", "GSM1"]
    assert "complete bijection" in proof["A"]["rule"]
    partial, proof = map_sample_columns(source, pd.DataFrame({"A": [1]}))
    assert list(partial.columns) == ["A"]
    assert not proof


def test_ambiguous_and_duplicate_targets_are_rejected():
    with pytest.raises(GeoError, match="Ambiguous"):
        map_sample_columns(series(["same", "same"]), pd.DataFrame({"same": [1]}))
    with pytest.raises(GeoError, match="same GEO sample"):
        map_sample_columns(series(["A"]), pd.DataFrame({"GSM1": [1], "A": [2]}))


def test_featurecounts_annotations_are_not_expression_columns():
    from cell_ledger.bulk import parse_matrix

    raw = (
        b"Geneid\tChr\tStart\tEnd\tStrand\tLength\tA\tB\ng1\tchr1;chr1\t1;4\t3;6\t+;+\t6\t10\t20\n"
    )
    matrix = parse_matrix(raw)
    assert list(matrix.columns) == ["A", "B"]
    assert matrix.loc["g1", "A"] == 10
    assert matrix.attrs["gene_annotation"]["Chr"] == ["chr1;chr1"]
    assert matrix.attrs["gene_annotation"]["gene_id"] == ["g1"]
    # Arbitrary text columns are still rejected, not silently discarded.
    with pytest.raises(GeoError, match="non-numeric"):
        parse_matrix(b"gene\tnotes\tGSM1\ng1\tannotation\t10\n")

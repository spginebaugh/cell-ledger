import pytest
from pydantic import ValidationError

from cell_ledger.samplesheet import Assay, Sample, SampleSheet


def _sample(gsm: str, condition: str) -> Sample:
    return Sample(gsm=gsm, title=f"{condition} rep", condition=condition, cell_type="T cell")


def test_sample_sheet_round_trips_to_dataframe() -> None:
    sheet = SampleSheet(
        gse="GSE12345",
        assay=Assay.BULK,
        samples=[_sample("GSM1", "disease"), _sample("GSM2", "control")],
    )
    df = sheet.to_dataframe()
    assert list(df.index) == ["GSM1", "GSM2"]
    assert df.loc["GSM1", "condition"] == "disease"
    assert "raw" not in df.columns


def test_duplicate_gsm_rejected() -> None:
    with pytest.raises(ValidationError, match="duplicate GSM"):
        SampleSheet(
            gse="GSE1",
            assay=Assay.SINGLE_CELL,
            samples=[_sample("GSM1", "a"), _sample("GSM1", "b")],
        )


def test_accession_patterns_enforced() -> None:
    with pytest.raises(ValidationError):
        Sample(gsm="not-an-accession", title="x")

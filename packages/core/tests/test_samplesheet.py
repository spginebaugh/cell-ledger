import pytest
from pydantic import ValidationError

from cell_ledger.samplesheet import Assay, Group, Sample, SampleSheet


def _sample(gsm: str, condition: str, group: Group = Group.UNKNOWN) -> Sample:
    return Sample(
        gsm=gsm, title=f"{condition} rep", condition=condition, cell_type="T cell", group=group
    )


def test_sample_sheet_round_trips_to_dataframe() -> None:
    sheet = SampleSheet(
        gse="GSE12345",
        assay=Assay.BULK,
        samples=[_sample("GSM1", "disease", Group.CASE), _sample("GSM2", "control", Group.CONTROL)],
    )
    df = sheet.to_dataframe()
    assert list(df.index) == ["GSM1", "GSM2"]
    assert df.loc["GSM1", "condition"] == "disease"
    assert df.loc["GSM1", "group"] == "case"
    assert "raw" not in df.columns
    assert sheet.group_counts() == {Group.CASE: 1, Group.CONTROL: 1}
    assert sheet.subset(["GSM2"]).gsms == ["GSM2"]


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


def test_evidence_must_be_verbatim_from_record() -> None:
    raw = {"disease state": "sepsis", "tissue": "blood"}
    ok = Sample(
        gsm="GSM1", title="S1", raw=raw, group=Group.CASE, evidence=["disease state: sepsis"]
    )
    assert ok.group is Group.CASE
    with pytest.raises(ValidationError, match="evidence not found"):
        Sample(
            gsm="GSM1", title="S1", raw=raw, group=Group.CASE, evidence=["disease: septic shock"]
        )
    # title and source_name are part of the record too
    Sample(gsm="GSM1", title="LADC17", source_name="LUAD", raw=raw, evidence=["LUAD", "LADC"])


def test_low_confidence_sets_needs_review() -> None:
    assert Sample(gsm="GSM1", title="x", confidence=0.5).needs_review is True
    assert Sample(gsm="GSM1", title="x", confidence=0.9).needs_review is False

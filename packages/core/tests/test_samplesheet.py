import pytest
from pydantic import ValidationError

from cell_ledger.samplesheet import Assay, Group, Sample, SampleSheet


def _sample(gsm: str, condition: str, group: Group = Group.UNKNOWN) -> Sample:
    raw = {"condition": condition}
    return Sample(
        gsm=gsm,
        title=f"{condition} rep",
        condition=condition,
        cell_type="T cell",
        group=group,
        raw=raw,
        evidence=[f"condition: {condition}"] if group is not Group.UNKNOWN else [],
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


def test_labels_require_record_and_evidence() -> None:
    with pytest.raises(ValidationError, match="no raw GEO record"):
        Sample(gsm="GSM1", title="x", group=Group.CASE, evidence=["x"])
    with pytest.raises(ValidationError, match="no evidence cited"):
        Sample(gsm="GSM1", title="x", group=Group.CONTROL, raw={"a": "b"})
    with pytest.raises(ValidationError, match="empty evidence"):
        Sample(gsm="GSM1", title="x", group=Group.CASE, raw={"a": "b"}, evidence=[""])
    # unknown samples may carry a record without citing anything
    Sample(gsm="GSM1", title="x", raw={"a": "b"})


def test_repeated_keys_cite_verbatim_lines() -> None:
    lines = ["tissue: blood", "tissue: blood again"]
    raw = {"tissue": "blood", "tissue.2": "blood again"}
    ok = Sample(
        gsm="GSM1",
        title="x",
        group=Group.CASE,
        raw=raw,
        raw_lines=lines,
        evidence=["tissue: blood again"],
    )
    assert ok.has_record


def test_low_confidence_sets_needs_review() -> None:
    assert Sample(gsm="GSM1", title="x", confidence=0.5).needs_review is True
    assert Sample(gsm="GSM1", title="x", confidence=0.9).needs_review is False

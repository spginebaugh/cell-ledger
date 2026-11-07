import pytest
from pydantic import ValidationError

from cell_ledger.samplesheet import Assay, Contrast, ContrastStatus, Group, Sample, SampleSheet


def _s(gsm: str, group: Group) -> Sample:
    return Sample(
        gsm=gsm,
        title=gsm,
        group=group,
        time_point="24h",
        raw={"g": group.value},
        evidence=[f"g: {group.value}"],
    )


def _sheet(n_case: int = 3, n_ctrl: int = 3) -> SampleSheet:
    samples = [_s(f"GSM{i}", Group.CASE) for i in range(1, n_case + 1)] + [
        _s(f"GSM{100 + i}", Group.CONTROL) for i in range(1, n_ctrl + 1)
    ]
    return SampleSheet(gse="GSE1", assay=Assay.BULK, samples=samples)


def _contrast(sheet: SampleSheet, **kw: object) -> Contrast:
    case = [s.gsm for s in sheet.samples if s.group is Group.CASE]
    ctrl = [s.gsm for s in sheet.samples if s.group is Group.CONTROL]
    kw.setdefault("status", ContrastStatus.CONFIRMED)
    return Contrast(
        gse="GSE1",
        name="case_vs_ctrl",
        case_label="case",
        control_label="ctrl",
        case_gsms=case,
        control_gsms=ctrl,
        **kw,  # type: ignore[arg-type]
    )


def test_clean_contrast_has_no_problems() -> None:
    sheet = _sheet()
    assert _contrast(sheet).problems(sheet) == []


def test_too_few_replicates_is_a_problem() -> None:
    sheet = _sheet(n_case=2)
    assert any("fewer than 3" in p for p in _contrast(sheet).problems(sheet))


def test_arm_disagreeing_with_group_label_is_a_problem() -> None:
    sheet = _sheet()
    c = _contrast(sheet)
    swapped = Contrast(
        **{**c.model_dump(), "case_gsms": c.control_gsms, "control_gsms": c.case_gsms}
    )
    assert any("labelled control" in p for p in swapped.problems(sheet))


def test_unknown_gsm_and_blocked_status_and_restriction() -> None:
    sheet = _sheet()
    c = _contrast(sheet, status=ContrastStatus.BLOCKED, rationale="paired design")
    assert any("blocked" in p for p in c.problems(sheet))
    c = _contrast(sheet, restricted_to={"time_point": "6h"})
    assert any("restricted to" in p for p in c.problems(sheet))
    c = _contrast(sheet).model_copy(update={"case_gsms": ["GSM1", "GSM2", "GSM999"]})
    assert any("not in sample sheet" in p for p in c.problems(sheet))


def test_proposed_contrast_is_not_runnable() -> None:
    sheet = _sheet()
    c = _contrast(sheet, status=ContrastStatus.PROPOSED)
    assert any("only proposed" in p for p in c.problems(sheet))


def test_qualifications_for_uncertain_labels() -> None:
    sheet = _sheet()
    assert _contrast(sheet).qualifications(sheet) == []
    c = _contrast(sheet, status=ContrastStatus.UNCERTAIN, rationale="two controls plausible")
    assert any("uncertain" in q for q in c.qualifications(sheet))
    low = _contrast(sheet, confidence=0.1)
    assert any("confidence 0.10" in q for q in low.qualifications(sheet))
    sheet.samples[0].needs_review = True
    assert any("need review" in q for q in _contrast(sheet).qualifications(sheet))


def test_arms_must_be_disjoint_and_unique() -> None:
    with pytest.raises(ValidationError, match="both arms"):
        Contrast(
            gse="GSE1",
            name="x",
            case_label="a",
            control_label="b",
            case_gsms=["GSM1"],
            control_gsms=["GSM1"],
        )
    with pytest.raises(ValidationError, match="duplicate"):
        Contrast(
            gse="GSE1",
            name="x",
            case_label="a",
            control_label="b",
            case_gsms=["GSM1", "GSM1"],
            control_gsms=["GSM2"],
        )

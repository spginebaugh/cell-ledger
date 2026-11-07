import json

import pytest

from evals.cases import CASES_DIR, Case, Suite, load_suite

from .conftest import make_case


def test_shipped_cases_load_and_match_file_names() -> None:
    suite = load_suite(CASES_DIR)
    assert {c.id for c in suite.cases} == {p.stem for p in CASES_DIR.glob("*.json")}
    assert all(c.status == "draft" for c in suite.cases), "drafts until a reviewer signs off"


@pytest.mark.parametrize(
    "overrides, match",
    [
        ({"expected_action": "ask"}, "clarification_targets"),
        ({"expected_action": "ask", "clarification_targets": [[""]]}, "non-empty"),
        ({"answers": ["x"]}, "answers only apply"),
        ({"expected_action": "decline"}, "cannot have positives"),
        ({"reviewed_by": ""}, "names its reviewer"),
        ({"pool": {}}, "needs a positive"),
        ({"pool": {"GSM1": {"relevant": True, "eligible": True}}}, "GSE accessions"),
        (
            {
                "pool": {
                    "GSE164073": {"relevant": True, "eligible": True},
                    "GSE250219": {"relevant": True, "eligible": None},
                }
            },
            "unjudged pool entries",
        ),
    ],
)
def test_invalid_cases_are_rejected(overrides: dict, match: str) -> None:
    with pytest.raises(ValueError, match=match):
        make_case(**overrides)


def test_draft_cases_may_be_incomplete() -> None:
    case = make_case(status="draft", reviewed_by="", pool={})
    assert case.positives() == set()


def test_digest_covers_prompt_and_answers_only() -> None:
    a = make_case()
    assert a.digest() == make_case(notes="different", tags=["x"]).digest()
    assert a.digest() != make_case(prompt="other question?").digest()
    asks = make_case(
        expected_action="ask", clarification_targets=[["control"]], answers=["healthy"]
    )
    assert (
        asks.digest()
        != make_case(expected_action="ask", clarification_targets=[["control"]]).digest()
    )
    assert asks.second_turn_action == "proceed"


def test_suite_rejects_duplicate_ids_and_misnamed_files(tmp_path) -> None:
    with pytest.raises(ValueError, match="duplicate"):
        Suite(cases=[make_case(), make_case()])
    (tmp_path / "wrong.json").write_text(json.dumps(make_case().model_dump()))
    with pytest.raises(ValueError, match="file name must match"):
        load_suite(tmp_path)
    with pytest.raises(ValueError, match="no case files"):
        load_suite(tmp_path / "empty")


def test_judged_and_positive_semantics() -> None:
    case = make_case(
        status="draft",
        reviewed_by="",
        pool={
            "GSE1": {"relevant": True, "eligible": True},
            "GSE2": {"relevant": True, "eligible": False},
            "GSE3": {"relevant": None, "eligible": False},
            "GSE4": {},
        },
    )
    assert case.positives() == {"GSE1"}
    assert set(case.judged()) == {"GSE1", "GSE2"}
    assert Case.model_validate(case.model_dump()).pool["GSE4"].judged is False

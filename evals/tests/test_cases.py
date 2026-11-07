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


@pytest.mark.parametrize(
    "entry, match",
    [
        ({"case_gsms": ["GSM1"]}, "both"),
        ({"relevant": False, "case_gsms": ["GSM1"], "control_gsms": ["GSM2"]}, "relevant"),
        ({"case_gsms": ["GSM1"], "control_gsms": ["GSE2"]}, "not GSM"),
        ({"case_gsms": ["GSM1"], "control_gsms": ["GSM1"]}, "twice"),
        ({"case_gsms": ["GSM1"], "control_gsms": ["GSM2"], "optional_gsms": ["GSM2"]}, "optional"),
    ],
)
def test_sample_arms_are_validated(entry: dict, match: str) -> None:
    base = {"relevant": True, "eligible": True, "reviewed_by": "t"}
    with pytest.raises(ValueError, match=match):
        make_case(pool={"GSE1": {**base, **entry}})
    ok = make_case(pool={"GSE1": {**base, "case_gsms": ["GSM1"], "control_gsms": ["GSM2"]}})
    assert ok.pool["GSE1"].has_arms


def test_also_acceptable_actions() -> None:
    case = make_case(expected_action="no_results", pool={}, also_acceptable=["ask"])
    assert case.action_ok("no_results") and case.action_ok("ask") and not case.action_ok("proceed")


def test_shipped_cases_arms_are_consistent() -> None:
    suite = load_suite(CASES_DIR)
    for c in suite.cases:
        for gse, e in c.pool.items():
            if e.has_arms:
                assert e.positive, (c.id, gse)
                assert len(e.case_gsms or []) >= 3 and len(e.control_gsms or []) >= 3, (c.id, gse)


def test_any_case_may_carry_a_fallback_answer_and_ask_only_cases_skip_recall() -> None:
    proceed = make_case(answers=["restating the prompt"])
    assert proceed.scores_recall and proceed.second_turn_action == "proceed"
    ask_only = make_case(expected_action="ask", clarification_targets=[["x"]])
    assert not ask_only.scores_recall
    asked = make_case(expected_action="ask", clarification_targets=[["x"]], answers=["y"])
    assert asked.scores_recall

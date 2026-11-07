from __future__ import annotations

import json
from typing import Any

import pytest

from evals.cases import Suite
from evals.records import RunRecord, Turn, Verification
from evals.report import render
from evals.scoring import score, score_record, update_queue

from .conftest import conditions, make_case


def record(case, system: str = "specialist", **kw: Any) -> RunRecord:
    turns = kw.pop("turns", None) or [Turn(action=kw.get("final_action", "proceed"))]
    base: dict[str, Any] = {
        "case_id": case.id,
        "system": system,
        "repeat": 1,
        "conditions": conditions(system, case),
        "turns": turns,
        "final_action": turns[-1].action,
        "input_tokens": 100,
        "output_tokens": 10,
        "elapsed_seconds": 4.0,
    }
    base.update(kw)
    return RunRecord.model_validate(base)


POOL = {
    "GSE1": {"relevant": True, "eligible": True, "reviewed_by": "t"},
    "GSE2": {"relevant": True, "eligible": True, "reviewed_by": "t"},
    "GSE3": {"relevant": False, "eligible": True, "reviewed_by": "t", "rationale": "mouse"},
    "GSE4": {"relevant": True, "eligible": False, "reviewed_by": "t"},
}


def test_retrieval_metrics_and_miss_kinds() -> None:
    case = make_case(pool=POOL)
    rec = record(
        case,
        candidates=["GSE1", "GSE3", "GSE9", "GSE4"],
        rejected=["GSE2"],
        seen=["GSE1", "GSE2", "GSE3"],
        per_query={"q1": ["GSE1", "GSE2"], "q2": ["GSE3"]},
        verification=Verification(eligible=["GSE1", "GSE3", "GSE9"], exists_only=["GSE4"]),
    )
    row = score_record(case, rec)
    assert row["hits"] == ["GSE1"]
    assert row["wrong"] == {"GSE3": "irrelevant", "GSE4": "ineligible"}
    assert row["unjudged"] == ["GSE9"]
    assert row["recall"] == {"n": 1, "d": 2, "value": 0.5}
    assert row["precision"] == {"n": 1, "d": 3, "value": pytest.approx(1 / 3)}
    assert row["misses"] == {"GSE2": "rejected"}
    assert row["ineligible_returned"] == ["GSE4"] and row["fabricated"] == []
    assert row["action_correct"] is True and row["passed"] is False
    assert row["queries"] == 2 and row["seen"] == 3


def test_miss_kinds_never_returned_ignored_and_baseline_not_named() -> None:
    case = make_case(pool=POOL)
    spec = record(case, candidates=[], seen=["GSE2"], final_action="no_results")
    assert score_record(case, spec)["misses"] == {"GSE1": "never_returned", "GSE2": "ignored"}
    base = record(
        case, "baseline", candidates=["GSE777"], verification=Verification(missing=["GSE777"])
    )
    row = score_record(case, base)
    assert row["misses"] == {"GSE1": "not_named", "GSE2": "not_named"}
    assert row["fabricated"] == ["GSE777"] and row["passed"] is False
    # GEO settled it: a fabricated accession is wrong without a human verdict and never queued.
    assert row["wrong"] == {"GSE777": "fabricated"} and row["unjudged"] == []
    assert row["precision"] == {"n": 0, "d": 1, "value": 0.0}


def test_ask_case_targets_and_second_turn() -> None:
    case = make_case(
        expected_action="ask",
        clarification_targets=[["control", "normal"], ["tissue"]],
        answers=["adjacent normal"],
        pool=POOL,
    )
    turns = [Turn(action="ask"), Turn(answers=["adjacent normal"], action="proceed")]
    rec = record(
        case,
        turns=turns,
        questions=[{"question": "Which control?", "options": ["adjacent normal"], "why": ""}],
        candidates=["GSE1", "GSE2"],
        seen=["GSE1", "GSE2"],
        verification=Verification(eligible=["GSE1", "GSE2"]),
    )
    row = score_record(case, rec)
    assert row["asked"] and row["action_correct"]
    assert row["targets"] == {"n": 1, "d": 2, "value": 0.5}  # tissue never came up
    assert row["second_turn_correct"] is True and row["turns"] == 2
    assert row["recall"]["value"] == 1.0 and row["passed"] is True

    silent = record(
        case,
        candidates=["GSE1", "GSE2"],
        seen=["GSE1", "GSE2"],
        verification=Verification(eligible=["GSE1", "GSE2"]),
    )
    row = score_record(case, silent)
    assert row["asked"] is False and row["action_correct"] is False
    assert row["targets"] == {"n": 0, "d": 2, "value": 0.0} and row["passed"] is False


def test_decline_and_error_rows() -> None:
    case = make_case(expected_action="decline", pool={}, status="draft", reviewed_by="")
    rec = record(case, final_action="decline", out_of_scope="mouse only")
    row = score_record(case, rec)
    assert row["action_correct"] and row["passed"] and row["recall"]["value"] is None
    err = record(case, turns=[Turn(action="error", error="boom")], error="boom")
    row = score_record(case, err)
    assert row["first_action"] == "error" and not row["passed"] and row["error"] == "boom"


def test_suite_score_pairing_queue_and_report(tmp_path) -> None:
    proceed = make_case(pool=POOL)
    asks = make_case(
        id="ask_case",
        expected_action="ask",
        clarification_targets=[["control"]],
        pool={"GSE1": POOL["GSE1"]},
        status="draft",
        reviewed_by="",
    )
    suite = Suite(cases=[proceed, asks])
    records = [
        record(
            proceed,
            candidates=["GSE1", "GSE2", "GSE50"],
            seen=["GSE1", "GSE2", "GSE50"],
            verification=Verification(eligible=["GSE1", "GSE2", "GSE50"]),
            candidate_details={"GSE50": {"title": "New series", "why": "looks right"}},
        ),
        record(
            proceed,
            repeat=2,
            candidates=["GSE1"],
            seen=["GSE1", "GSE2"],
            verification=Verification(eligible=["GSE1"]),
        ),
        record(
            proceed,
            "baseline",
            candidates=["GSE1", "GSE50", "GSE8888"],
            verification=Verification(eligible=["GSE1", "GSE50"], missing=["GSE8888"]),
        ),
        record(
            asks,
            turns=[Turn(action="ask")],
            questions=[{"question": "which control?", "options": [], "why": ""}],
        ),
    ]
    result = score(suite, records)
    spec, base = result["summaries"]["specialist"], result["summaries"]["baseline"]
    assert spec["runs"] == 3 and spec["cases"] == 2 and base["runs"] == 1
    # Macro recall averages the two repeats of the proceed case (1.0 and 0.5); the ask case has
    # no scripted answers, so it ends at the question and its recall is not scored.
    assert spec["recall_macro"]["mean"] == pytest.approx(0.75)
    assert spec["recall_pooled"] == {"n": 3, "d": 4, "value": 0.75}
    assert spec["should_ask"] == {"n": 1, "d": 1, "value": 1.0}
    assert spec["false_ask"] == {"n": 0, "d": 2, "value": 0.0}
    assert spec["unjudged_total"] == 1 and base["fabricated_total"] == 1
    assert spec["misses"] == {"ignored": 1} and base["misses"] == {"not_named": 1}
    assert spec["input_tokens_per_run"]["mean"] == 100
    assert result["pairing_problems"] == ["ask_case: run by one system only"]
    assert result["draft_cases"] == ["ask_case"] and result["comparison_ready"] is False

    queue_path = tmp_path / "queue.json"
    queue = update_queue(result, records, suite, path=queue_path)
    assert [(e["case_id"], e["gse"], sorted(e["systems"])) for e in queue] == [
        ("pdac_tumor_vs_normal", "GSE50", ["baseline", "specialist"])
    ]
    assert queue[0]["title"] == "New series" and queue[0]["runs"] == ["run1"]
    # Once the pool judges GSE50 the entry leaves the queue.
    judged = make_case(
        pool={**POOL, "GSE50": {"relevant": False, "eligible": True, "reviewed_by": "t"}}
    )
    assert update_queue(result, records, Suite(cases=[judged, asks]), path=queue_path) == []
    assert json.loads(queue_path.read_text()) == []

    md = render(result)
    assert "| Metric | baseline | specialist |" in md
    assert "GSE8888" in md and "never_returned" in md and "ask_case" in md


def test_changed_case_or_unknown_case() -> None:
    case = make_case(pool=POOL)
    rec = record(case)
    with pytest.raises(ValueError, match="changed since this run"):
        score(Suite(cases=[make_case(pool=POOL, prompt="a different prompt?")]), [rec])
    result = score(Suite(cases=[make_case(id="other", pool=POOL)]), [rec])
    assert result["unknown_cases"] == [case.id] and result["rows"] == []


def test_reviewed_only_drops_draft_cases() -> None:
    draft = make_case(id="draft_case", status="draft", reviewed_by="", pool=POOL)
    reviewed = make_case(pool=POOL)
    suite = Suite(cases=[draft, reviewed])
    rows = score(suite, [record(draft), record(reviewed)], reviewed_only=True)["rows"]
    assert [r["case_id"] for r in rows] == [reviewed.id]


def test_sample_level_metrics_on_reviewed_arms() -> None:
    pool = {
        "GSE1": {**POOL["GSE1"], "case_gsms": ["GSM1", "GSM2", "GSM3"],
                 "control_gsms": ["GSM4", "GSM5", "GSM6"]},
        "GSE2": {**POOL["GSE2"], "case_gsms": ["GSM7"], "control_gsms": ["GSM8"]},
    }  # fmt: skip
    case = make_case(pool=pool)
    rec = record(
        case,
        candidates=["GSE1", "GSE2"],
        verification=Verification(eligible=["GSE1", "GSE2"]),
        selections={
            # one organoid too many in the case arm, one control missed
            "GSE1": {"case": ["GSM1", "GSM2", "GSM3", "GSM9"], "control": ["GSM4", "GSM5"]},
            "GSE2": {"case": ["GSM7"], "control": ["GSM8"], "unclear": ["GSM10"]},
        },
    )
    row = score_record(case, rec)
    assert row["sample_precision"] == {"n": 7, "d": 8, "value": 7 / 8}
    assert row["sample_recall"] == {"n": 7, "d": 8, "value": 7 / 8}
    assert row["subsets_exact"] == {"n": 1, "d": 2, "value": 0.5}
    # swapped arms are wrong in both
    swapped = record(
        case,
        candidates=["GSE2"],
        verification=Verification(eligible=["GSE2"]),
        selections={"GSE2": {"case": ["GSM8"], "control": ["GSM7"]}},
    )
    assert score_record(case, swapped)["sample_recall"]["value"] == 0.0
    # positives without reviewed arms do not count either way
    plain = make_case(pool=POOL)
    assert score_record(plain, rec)["subsets_exact"] == {"n": 0, "d": 0, "value": None}


def test_also_acceptable_first_action_counts_as_correct() -> None:
    case = make_case(expected_action="no_results", pool={}, also_acceptable=["ask"])
    row = score_record(case, record(case, turns=[Turn(action="ask")], final_action="ask"))
    assert row["action_correct"] is True


def test_ask_only_cases_do_not_score_recall_or_misses() -> None:
    case = make_case(pool=POOL, expected_action="ask", clarification_targets=[["control"]])
    turn = Turn(action="ask")
    rec = record(
        case,
        turns=[turn],
        candidates=["GSE1"],
        verification=Verification(eligible=["GSE1"]),
        questions=[{"question": "Which control?", "options": [], "why": ""}],
    )
    row = score_record(case, rec)
    assert row["recall"] == {"n": 0, "d": 0, "value": None} and row["misses"] == {}
    assert row["precision"] == {"n": 1, "d": 1, "value": 1.0}
    assert row["questions"] == ["Which control?"] and row["passed"] is True


def test_optional_samples_are_not_scored_either_way() -> None:
    arms = {
        "case_gsms": ["GSM1", "GSM2", "GSM3"],
        "control_gsms": ["GSM4", "GSM5", "GSM6"],
        "optional_gsms": ["GSM9"],
    }
    pool = {"GSE1": {**POOL["GSE1"], **arms}}
    case = make_case(pool=pool)
    for chosen in (["GSM1", "GSM2", "GSM3"], ["GSM1", "GSM2", "GSM3", "GSM9"]):
        rec = record(
            case,
            candidates=["GSE1"],
            verification=Verification(eligible=["GSE1"]),
            selections={"GSE1": {"case": chosen, "control": ["GSM4", "GSM5", "GSM6"]}},
        )
        row = score_record(case, rec)
        assert row["subsets_exact"]["value"] == 1.0 and row["sample_precision"]["value"] == 1.0


def test_report_lists_questions_verbatim() -> None:
    case = make_case(answers=["restated"])
    rec = record(
        case,
        turns=[Turn(action="ask"), Turn(action="proceed")],
        questions=[{"question": "Which inhibitor class?", "options": [], "why": ""}],
    )
    text = render(score(Suite(cases=[case]), [rec]))
    assert "## Questions asked" in text
    assert f"**{case.id}** · specialist r1 (expected proceed)" in text
    assert "  - Which inhibitor class?" in text

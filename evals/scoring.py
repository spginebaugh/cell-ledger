"""Score run records against cases. Nothing here infers gold from a run: a candidate without
a verdict in the pool is queued for a human, not counted either way."""

from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from typing import Any

from evals.cases import Case, Suite
from evals.records import RunRecord

QUEUE_PATH = Path(__file__).parent / "review_queue.json"
MissKind = str  # never_returned | rejected | ignored | not_named


def ratio(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "n": numerator,
        "d": denominator,
        "value": numerator / denominator if denominator else None,
    }


def _question_text(questions: list[dict[str, Any]]) -> str:
    parts = []
    for q in questions:
        parts.append(str(q.get("question", "")))
        parts.extend(str(o) for o in q.get("options", []) or [])
        parts.append(str(q.get("why", "")))
    return " ".join(parts).casefold()


def score_record(case: Case, rec: RunRecord) -> dict[str, Any]:
    positives = case.positives()
    judged = case.judged()
    candidates = list(dict.fromkeys(rec.candidates))
    hits = [g for g in candidates if g in positives]
    fabricated = rec.verification.missing + rec.verification.invalid
    ineligible = rec.verification.exists_only
    # GEO's own verdict settles a candidate without a human: absent or ineligible is wrong.
    mechanical = {g: "fabricated" for g in fabricated} | {g: "ineligible" for g in ineligible}
    judged_candidates = [g for g in candidates if g in judged or g in mechanical]
    unjudged = [g for g in candidates if g not in judged and g not in mechanical]
    wrong: dict[str, str] = {}
    for g in judged_candidates:
        if g in positives:
            continue
        if g in mechanical:
            wrong[g] = mechanical[g]
        else:
            wrong[g] = "ineligible" if judged[g].eligible is False else "irrelevant"
    misses: dict[str, MissKind] = {}
    for g in sorted(positives - set(candidates)):
        if rec.system == "baseline":
            misses[g] = "not_named"
        elif g in rec.seen:
            misses[g] = "rejected" if g in rec.rejected else "ignored"
        else:
            misses[g] = "never_returned"

    first = rec.turns[0].action
    asked = first == "ask"
    action_correct = first == case.expected_action
    targets_hit = None
    if case.expected_action == "ask":
        text = _question_text(rec.questions)
        targets_hit = sum(
            any(word.casefold() in text for word in words) for words in case.clarification_targets
        )
    second_turn_correct = None
    if len(rec.turns) > 1:
        second_turn_correct = rec.turns[1].action == case.second_turn_action

    passed = (
        rec.error is None
        and action_correct
        and not fabricated
        and not ineligible
        and not wrong
        and second_turn_correct is not False
        and (not positives or bool(hits))
    )
    return {
        "case_id": case.id,
        "system": rec.system,
        "repeat": rec.repeat,
        "case_status": case.status,
        "expected_action": case.expected_action,
        "first_action": first,
        "action_correct": action_correct,
        "asked": asked,
        "targets": ratio(targets_hit or 0, len(case.clarification_targets))
        if targets_hit is not None
        else None,
        "second_turn_correct": second_turn_correct,
        "turns": len(rec.turns),
        "candidates": candidates,
        "hits": hits,
        "wrong": wrong,
        "unjudged": unjudged,
        "recall": ratio(len(hits), len(positives)),
        "precision": ratio(len(hits), len(judged_candidates)),
        "misses": misses,
        "fabricated": fabricated,
        "ineligible_returned": ineligible,
        "invented_dropped": rec.invented,
        "queries": len(rec.per_query),
        "seen": len(rec.seen),
        "input_tokens": rec.input_tokens,
        "output_tokens": rec.output_tokens,
        "web_search_requests": rec.web_search_requests,
        "elapsed_seconds": rec.elapsed_seconds,
        "error": rec.error,
        "passed": passed,
    }


def _spread(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        return {"mean": None, "min": None, "max": None, "n": 0}
    return {"mean": mean(values), "min": min(values), "max": max(values), "n": len(values)}


def _pooled(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    return ratio(sum(r[key]["n"] for r in rows), sum(r[key]["d"] for r in rows))


def summarize_system(rows: list[dict[str, Any]], scheduled: int) -> dict[str, Any]:
    """One system across every case and repeat. Macro means are over cases (each case's
    repeats averaged first) so a case run three times does not weigh three times."""
    by_case: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        by_case.setdefault(r["case_id"], []).append(r)

    def macro(key: str) -> dict[str, Any]:
        per_case = []
        for runs in by_case.values():
            vals = [r[key]["value"] for r in runs if r[key] and r[key]["value"] is not None]
            if vals:
                per_case.append(mean(vals))
        return _spread(per_case)

    expected_ask = [r for r in rows if r["expected_action"] == "ask"]
    expected_proceed = [r for r in rows if r["expected_action"] == "proceed"]
    misses = Counter(kind for r in rows for kind in r["misses"].values())
    return {
        "cases": len(by_case),
        "cases_scheduled": scheduled,
        "runs": len(rows),
        "errors": sum(1 for r in rows if r["error"]),
        "passed": ratio(sum(r["passed"] for r in rows), len(rows)),
        "action_accuracy": ratio(sum(r["action_correct"] for r in rows), len(rows)),
        "should_ask": ratio(sum(r["asked"] for r in expected_ask), len(expected_ask)),
        "false_ask": ratio(sum(r["asked"] for r in expected_proceed), len(expected_proceed)),
        "target_coverage": _pooled([r for r in rows if r["targets"]], "targets"),
        "second_turn_accuracy": ratio(
            sum(1 for r in rows if r["second_turn_correct"] is True),
            sum(1 for r in rows if r["second_turn_correct"] is not None),
        ),
        "recall_macro": macro("recall"),
        "precision_macro": macro("precision"),
        "recall_pooled": _pooled(rows, "recall"),
        "precision_pooled": _pooled(rows, "precision"),
        "candidates_total": sum(len(r["candidates"]) for r in rows),
        "unjudged_total": sum(len(r["unjudged"]) for r in rows),
        "wrong_total": sum(len(r["wrong"]) for r in rows),
        "fabricated_total": sum(len(r["fabricated"]) for r in rows),
        "ineligible_total": sum(len(r["ineligible_returned"]) for r in rows),
        "invented_dropped_total": sum(len(r["invented_dropped"]) for r in rows),
        "misses": dict(misses),
        "queries_per_run": _spread([r["queries"] for r in rows]),
        "input_tokens_per_run": _spread([r["input_tokens"] for r in rows]),
        "output_tokens_per_run": _spread([r["output_tokens"] for r in rows]),
        "web_search_requests_per_run": _spread([r["web_search_requests"] for r in rows]),
        "elapsed_seconds_per_run": _spread([r["elapsed_seconds"] for r in rows]),
    }


PAIRED_CONDITIONS = ("model", "effort", "geo_cache", "suite_sha256")


def score(suite: Suite, records: list[RunRecord], *, reviewed_only: bool = False) -> dict[str, Any]:
    cases = suite.by_id()
    if reviewed_only:
        cases = {k: c for k, c in cases.items() if c.status == "reviewed"}
    rows = []
    unknown = []
    for rec in records:
        case = cases.get(rec.case_id)
        if case is None:
            unknown.append(rec.case_id)
            continue
        if rec.conditions.case_sha256 != case.digest():
            raise ValueError(f"{rec.case_id}: the case changed since this run; re-run it")
        rows.append(score_record(case, rec))
    systems = sorted({r["system"] for r in rows})
    summaries = {
        s: summarize_system([r for r in rows if r["system"] == s], len(cases)) for s in systems
    }

    pairing: list[str] = []
    both = {"specialist", "baseline"}
    if both <= set(systems):
        run_cases = {s: {r["case_id"] for r in rows if r["system"] == s} for s in both}
        for missing in sorted(run_cases["specialist"] ^ run_cases["baseline"]):
            pairing.append(f"{missing}: run by one system only")
        spec = next(r for r in records if r.system == "specialist").conditions
        base = next(r for r in records if r.system == "baseline").conditions
        for field in PAIRED_CONDITIONS:
            if getattr(spec, field) != getattr(base, field):
                pairing.append(f"conditions differ on {field}")
    else:
        pairing.append("only one system was run; nothing to compare")

    draft = sorted({r["case_id"] for r in rows if r["case_status"] == "draft"})
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "suite_sha256": suite.digest(),
        "cases_scored": sorted({r["case_id"] for r in rows}),
        "draft_cases": draft,
        "unknown_cases": sorted(set(unknown)),
        "summaries": summaries,
        "pairing_problems": pairing,
        "comparison_ready": not pairing and not draft,
        "rows": rows,
        "note": "Recall and precision count only pool entries with a human verdict. Unjudged "
        "candidates are in the review queue. Draft cases are scored but the comparison is not "
        "ready until every scored case is reviewed.",
    }


def update_queue(
    result: dict[str, Any], records: list[RunRecord], suite: Suite, path: Path = QUEUE_PATH
) -> list[dict[str, Any]]:
    """Add every unjudged candidate to the review queue; drop entries the pool now judges."""
    queue: list[dict[str, Any]] = json.loads(path.read_text()) if path.exists() else []
    by_key = {(e["case_id"], e["gse"]): e for e in queue}
    details = {(r.case_id, g): d for r in records for g, d in r.candidate_details.items()}
    run_ids = {(r.case_id, r.system): r.conditions.run_id for r in records}
    for row in result["rows"]:
        for gse in row["unjudged"]:
            key = (row["case_id"], gse)
            entry = by_key.setdefault(
                key,
                {
                    "case_id": row["case_id"],
                    "gse": gse,
                    "title": details.get(key, {}).get("title", ""),
                    "why": details.get(key, {}).get("why", ""),
                    "case_hint": details.get(key, {}).get("case_hint", ""),
                    "control_hint": details.get(key, {}).get("control_hint", ""),
                    "systems": [],
                    "runs": [],
                    "first_seen": datetime.now(UTC).date().isoformat(),
                    "verdict": {
                        "relevant": None,
                        "eligible": None,
                        "rationale": "",
                        "reviewed_by": "",
                    },
                },
            )
            if row["system"] not in entry["systems"]:
                entry["systems"].append(row["system"])
            run_id = run_ids.get((row["case_id"], row["system"]))
            if run_id and run_id not in entry["runs"]:
                entry["runs"].append(run_id)
    cases = suite.by_id()
    kept = [
        e
        for e in by_key.values()
        if e["case_id"] not in cases
        or not cases[e["case_id"]].pool.get(e["gse"], None)
        or not cases[e["case_id"]].pool[e["gse"]].judged
    ]
    kept.sort(key=lambda e: (e["case_id"], e["gse"]))
    path.write_text(json.dumps(kept, indent=2, ensure_ascii=False) + "\n")
    return kept

"""Fail-closed scoring against independent gold; missing data is never a passing score."""

from __future__ import annotations

from evals.contracts import Benchmark, CaseGold, RunRecord, Snapshot, prompt_digest


def ratio(numerator: int, denominator: int) -> dict:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
    }


def score_case(case: CaseGold, record: RunRecord, snapshot: Snapshot) -> dict:
    if record.case_id != case.id or record.conditions.prompt_sha256 != prompt_digest(case):
        raise ValueError("Run does not match the exact case prompt and constraints")
    if record.conditions.snapshot_sha256 != snapshot.digest():
        raise ValueError("Run used a different source snapshot")
    positives = {gse for gse, study in case.studies.items() if study.relevant and study.eligible}
    critical: list[str] = []
    incomplete: list[str] = []
    all_ids = set(
        record.ranking
        + record.recommendations
        + [b.gse for b in record.bundles]
        + [s.gse for s in record.samples]
    )
    unverified = sorted(all_ids - set(snapshot.records))
    unjudged = sorted(all_ids - set(case.studies))
    nonexistent = sorted(
        gse for gse in all_ids if gse in snapshot.records and not snapshot.records[gse].exists
    )
    if unverified:
        incomplete.append("Unverified accession(s); do not label them fabricated without checking")
    if unjudged:
        incomplete.append("Output outside the adjudicated candidate pool")
    if nonexistent:
        critical.append("Cited verified nonexistent accessions")
    if len(record.ranking) != len(set(record.ranking)):
        critical.append("Duplicate ranking entries")
    if len(record.recommendations) != len(set(record.recommendations)):
        critical.append("Duplicate recommendations")
    if not set(record.recommendations) <= set(record.ranking):
        critical.append("Recommendations absent from recorded ranking")
    for gse in record.recommendations:
        if gse in case.studies and not case.studies[gse].eligible:
            critical.append(f"Recommended ineligible study: {gse}")
    max_datasets = int(case.constraints.get("max_datasets", 3))
    if len(record.recommendations) > max_datasets or len(record.bundles) > max_datasets:
        critical.append("Exceeded requested dataset limit")
    rank3 = record.recommendations[:3]
    rank10 = record.ranking[:10]
    correct3 = len(set(rank3) & positives)
    retrieved10 = len(set(rank10) & positives)
    # Missing slots cannot make abstention appear perfect. Returned precision is separate.
    answerable = case.expected_action == "proceed"
    slots = min(3, max_datasets, len(case.studies)) if answerable else 0
    metrics = {
        "precision_at_3_slots": ratio(correct3 if answerable else 0, slots),
        "precision_returned_at_3": ratio(correct3, len(rank3)) if answerable else ratio(0, 0),
        "recall_at_10_in_pool": ratio(retrieved10, len(positives)) if answerable else ratio(0, 0),
        "recommendation_count": len(record.recommendations),
        "verified_nonexistent_citations": len(nonexistent),
        "unverified_citations": len(unverified),
    }
    predictions = {}
    evidence_valid = evidence_total = metadata_correct = metadata_total = 0
    known_labels = labels_filled = 0
    confusion = {label: {"tp": 0, "fp": 0, "fn": 0} for label in ("case", "control")}
    for prediction in record.samples:
        key = (prediction.gse, prediction.gsm)
        if key in predictions:
            critical.append(f"Duplicate sample prediction: {key}")
        predictions[key] = prediction
        source = snapshot.records.get(prediction.gse)
        if source is None or prediction.gsm not in source.samples:
            critical.append(f"Sample absent from verified source: {prediction.gsm}")
        for field, value in prediction.fields.items():
            if value is None or value == "":
                continue
            evidence_total += 1
            evidence = prediction.evidence.get(field)
            valid = bool(
                evidence
                and evidence.gse == prediction.gse
                and evidence.gsm == prediction.gsm
                and snapshot.contains(evidence)
            )
            evidence_valid += int(valid)
            if not valid:
                critical.append(f"Missing or invalid field evidence: {prediction.gsm}.{field}")
    selected_studies = set(record.recommendations) | {b.gse for b in record.bundles}
    for gse, study in case.studies.items():
        # Optional candidates are not promised exports; retrieval metrics assess selection.
        if gse not in selected_studies:
            continue
        for gsm, sample in study.samples.items():
            prediction = predictions.get((gse, gsm))
            for field, expected in sample.fields.items():
                actual = prediction.fields.get(field) if prediction else None
                metadata_total += 1
                metadata_correct += int(prediction is not None and actual == expected)
                if expected is not None:
                    known_labels += 1
                    labels_filled += int(actual is not None and actual != "")
                if field == "group" and expected in {"case", "control"}:
                    if actual in {"case", "control"} and actual != expected:
                        critical.append(f"Swapped case/control label: {gsm}")
                    for label, counts in confusion.items():
                        counts["tp"] += int(actual == label and expected == label)
                        counts["fp"] += int(actual == label and expected != label)
                        counts["fn"] += int(actual != label and expected == label)
    f1 = {
        label: ratio(2 * c["tp"], 2 * c["tp"] + c["fp"] + c["fn"]) for label, c in confusion.items()
    }
    metrics.update(
        {
            "field_accuracy": ratio(metadata_correct, metadata_total),
            "known_field_completeness": ratio(labels_filled, known_labels),
            "field_evidence_validity": ratio(evidence_valid, evidence_total),
            "group_f1": f1,
            "group_confusion": confusion,
        }
    )
    expected_bundles = {
        gse
        for gse, study in case.studies.items()
        if study.relevant and study.eligible and study.expected_gsms
    }
    bundles = {}
    correct_bundles = 0
    executed = workflow_passed = 0
    for bundle in record.bundles:
        if bundle.gse in bundles:
            critical.append(f"Duplicate bundle: {bundle.gse}")
        bundles[bundle.gse] = bundle
        study = case.studies.get(bundle.gse)
        if study is None:
            continue
        if not study.relevant or not study.eligible:
            critical.append(f"Exported nonqualifying dataset: {bundle.gse}")
        if len(set(bundle.sample_ids)) != len(bundle.sample_ids):
            critical.append(f"Duplicate bundle sample identities: {bundle.gse}")
        if study.expected_gsms and set(bundle.sample_ids) != set(study.expected_gsms):
            critical.append(f"Wrong exported sample identities: {bundle.gse}")
        if study.units is not None and bundle.units != study.units:
            critical.append(f"Wrong expression units: {bundle.gse}")
        if study.de_ready is False and bundle.de_ready:
            critical.append(f"Unsafe DE capability: {bundle.gse}")
        correct = (
            bundle.integrity_passed
            and set(bundle.sample_ids) == set(study.expected_gsms)
            and len(set(bundle.sample_ids)) == len(bundle.sample_ids)
            and (study.units is None or bundle.units == study.units)
            and (study.de_ready is None or bundle.de_ready == study.de_ready)
        )
        for gsm, expected_sample in study.samples.items():
            prediction = predictions.get((bundle.gse, gsm))
            if prediction is None or any(
                prediction.fields.get(k) != v for k, v in expected_sample.fields.items()
            ):
                correct = False
        correct_bundles += int(bundle.gse in expected_bundles and correct)
        if bundle.workflow_executed:
            executed += 1
            workflow_passed += int(bundle.workflow_passed is True and correct)
        if not bundle.integrity_passed:
            critical.append(f"Broken bundle: {bundle.gse}")
    minimum = int(case.constraints.get("min_datasets", 1))
    bundle_target = minimum if answerable and case.required_workflow != "none" else 0
    metrics["correct_bundle_completion"] = ratio(min(correct_bundles, bundle_target), bundle_target)
    metrics["executed_workflow_success"] = ratio(workflow_passed, executed)
    metrics["workflow_execution_coverage"] = ratio(executed, len(expected_bundles))
    actual_action = record.action if record.run_status == "complete" else "error"
    action_correct = actual_action == case.expected_action
    if case.expected_action == "ask" and actual_action == "ask":
        if not record.question_reviewed_by:
            incomplete.append("Clarification specificity has not been independently reviewed")
            action_correct = False
        if not set(case.clarification_targets) <= set(record.clarification_targets):
            action_correct = False
        if not record.questions:
            action_correct = False
    metrics["action_correct"] = action_correct
    metrics["should_ask"] = (
        ratio(int(actual_action == "ask"), int(case.expected_action == "ask"))
        if case.expected_action == "ask"
        else ratio(0, 0)
    )
    metrics["false_ask"] = (
        ratio(int(actual_action == "ask"), 1) if case.expected_action == "proceed" else ratio(0, 0)
    )
    metrics["elapsed_seconds"] = record.elapsed_seconds
    metrics["cost_usd"] = record.cost_usd
    metrics["human_corrections"] = record.human_corrections
    metrics["clarification_answers"] = record.clarification_answers
    metrics["false_abstention"] = (
        ratio(int(actual_action in {"ask", "decline", "no_results"}), 1)
        if case.expected_action == "proceed"
        else ratio(0, 0)
    )
    retrieval_complete = (
        bool(positives)
        and len(set(record.recommendations) & positives) >= minimum
        and set(record.recommendations) <= positives
    )
    if case.required_workflow == "none":
        metrics["promised_workflow_complete"] = retrieval_complete
    elif case.required_workflow == "load_only":
        metrics["promised_workflow_complete"] = (
            retrieval_complete and bundle_target > 0 and correct_bundles >= bundle_target
        )
    else:
        metrics["promised_workflow_complete"] = (
            retrieval_complete and bundle_target > 0 and workflow_passed >= bundle_target
        )
    if record.elapsed_seconds > record.conditions.time_budget_seconds:
        incomplete.append("Exceeded declared time budget; comparison conditions violated")
    if record.input_tokens is not None and record.output_tokens is not None:
        if record.input_tokens + record.output_tokens > record.conditions.token_budget:
            incomplete.append("Exceeded declared token budget; comparison conditions violated")
    else:
        incomplete.append("Token usage unmeasured; budget compliance cannot be verified")
    if record.run_status != "complete":
        critical.append(f"Run did not complete: {record.run_status}")
    if record.conditions.protocol != "frozen_pool":
        incomplete.append("Live-search run: frozen-pool recall is not a global retrieval score")
    return {
        "case_id": case.id,
        "split": case.split,
        "system": record.system,
        "metrics": metrics,
        "critical_errors": sorted(set(critical)),
        "incomplete": incomplete,
        "unverified_accessions": unverified,
        "unjudged_accessions": unjudged,
        "nonexistent_accessions": nonexistent,
        "valid_for_comparison": not critical and not incomplete,
    }


def compare(benchmark: Benchmark, snapshot: Snapshot, records: list[RunRecord]) -> dict:
    if not benchmark.frozen:
        raise ValueError("Freeze independently reviewed gold before scoring a comparison")
    benchmark.validate_sources(snapshot)
    cases = {case.id: case for case in benchmark.cases}
    indexed = {}
    rows = []
    for record in records:
        key = (record.case_id, record.system)
        if key in indexed:
            raise ValueError("Duplicate run for a case/system; select the preregistered attempt")
        if record.case_id not in cases:
            raise ValueError("Run contains an unknown benchmark case")
        indexed[key] = record
        rows.append(score_case(cases[record.case_id], record, snapshot))
    pairing_errors = []
    for case in benchmark.cases:
        pair = [indexed.get((case.id, system)) for system in ("specialist", "baseline")]
        if any(record is None for record in pair):
            pairing_errors.append(f"{case.id}: missing specialist or baseline run")
            continue
        left, right = pair
        assert left is not None and right is not None
        # Code differs by design; all experimental conditions must otherwise match.
        for field in (
            "model",
            "source_access",
            "execution_access",
            "time_budget_seconds",
            "token_budget",
            "protocol",
            "snapshot_sha256",
            "prompt_sha256",
            "attempt",
        ):
            if getattr(left.conditions, field) != getattr(right.conditions, field):
                pairing_errors.append(f"{case.id}: mismatched {field}")
        if left.conditions.attempt != 1:
            pairing_errors.append(
                f"{case.id}: non-first attempt requires a new preregistered protocol"
            )
    summaries = {}
    for split in ("development", "held_out"):
        split_cases = [case for case in benchmark.cases if case.split == split]
        for system in ("specialist", "baseline"):
            selected = [row for row in rows if row["split"] == split and row["system"] == system]
            summary = {
                "case_coverage": ratio(len(selected), len(split_cases)),
                "critical_error_count": sum(len(r["critical_errors"]) for r in selected),
                "incomplete_case_count": sum(bool(r["incomplete"]) for r in selected),
            }
            for name in (
                "precision_at_3_slots",
                "precision_returned_at_3",
                "recall_at_10_in_pool",
                "field_accuracy",
                "known_field_completeness",
                "field_evidence_validity",
                "correct_bundle_completion",
                "executed_workflow_success",
                "workflow_execution_coverage",
                "should_ask",
                "false_ask",
                "false_abstention",
            ):
                values = [r["metrics"][name] for r in selected]
                summary[name] = ratio(
                    sum(v["numerator"] for v in values), sum(v["denominator"] for v in values)
                )
            # Missing scheduled runs are failures in task-level completion, never dropped.
            answerable = [c for c in split_cases if c.expected_action == "proceed"]
            successful = sum(
                1
                for r in selected
                if cases[r["case_id"]] in answerable
                and r["metrics"]["promised_workflow_complete"]
                and r["metrics"]["action_correct"]
                and not r["critical_errors"]
                and not r["incomplete"]
            )
            summary["action_accuracy"] = ratio(
                sum(r["metrics"]["action_correct"] for r in selected), len(split_cases)
            )
            summary["critical_case_count"] = sum(bool(r["critical_errors"]) for r in selected)
            confusion = {
                label: {
                    key: sum(r["metrics"]["group_confusion"][label][key] for r in selected)
                    for key in ("tp", "fp", "fn")
                }
                for label in ("case", "control")
            }
            summary["group_f1"] = {
                label: ratio(2 * c["tp"], 2 * c["tp"] + c["fp"] + c["fn"])
                for label, c in confusion.items()
            }
            summary["answerable_task_completion"] = ratio(successful, len(answerable))
            summaries[f"{split}/{system}"] = summary
    return {
        "benchmark": benchmark.id,
        "version": benchmark.version,
        "data_kind": benchmark.data_kind,
        "pairing_errors": pairing_errors,
        "cases": rows,
        "summaries": summaries,
        "comparison_ready": benchmark.data_kind == "real"
        and not pairing_errors
        and bool(rows)
        and all(not row["incomplete"] for row in rows),
        "note": "Critical errors are results, not reasons to omit runs. No winner is inferred. "
        "Retrieval denominators are restricted to the reviewed frozen candidate pools.",
    }

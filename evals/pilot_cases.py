"""Stage-specific development checks. Selection approval never becomes analysis approval."""

from __future__ import annotations

from typing import Literal

from pydantic import Field, model_validator

from evals.contracts import Conditions, Evidence, StrictModel, digest
from evals.scoring import ratio

Stage = Literal["discovery", "selection"]


class FieldAnswer(StrictModel):
    value: str | None
    aliases: list[str] = Field(default_factory=list)
    evidence: list[Evidence] = Field(min_length=1)


class Disclosure(StrictModel):
    gse: str
    kind: Literal["not_in_count_header", "unresolved_model"]
    sample_ids: list[str]


class SelectionAnswer(StrictModel):
    sample_ids: list[str] = Field(min_length=1)
    fields: dict[str, dict[str, FieldAnswer]]
    disclosures: list[Disclosure] = Field(default_factory=list)
    unresolved_sample_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent_ids(self):
        if len(set(self.sample_ids)) != len(self.sample_ids):
            raise ValueError("Duplicate selected sample in reviewed answer")
        if set(self.fields) != set(self.sample_ids):
            raise ValueError("Every selected sample needs reviewed fields")
        if set(self.sample_ids) & set(self.unresolved_sample_ids):
            raise ValueError("Unresolved model assignments cannot enter the approved selection")
        return self


class PilotCase(StrictModel):
    id: str
    stage: Stage
    prompt: str
    constraints: dict[str, str | int | bool]
    candidate_gses: list[str]
    acceptable_gses: list[str] = Field(min_length=1)
    selections: dict[str, SelectionAnswer] = Field(default_factory=dict)
    review_references: list[str] = Field(min_length=1)
    scope: str
    split: Literal["development"] = "development"

    @model_validator(mode="after")
    def valid_case(self):
        minimum = self.constraints.get("min_datasets", 1)
        maximum = self.constraints.get("max_datasets", 20)
        if (
            type(minimum) is not int
            or type(maximum) is not int
            or not 1 <= minimum <= maximum <= 20
        ):
            raise ValueError("Dataset bounds require integers: 1 <= minimum <= maximum <= 20")
        if len(set(self.candidate_gses)) != len(self.candidate_gses):
            raise ValueError("Duplicate candidate identities")
        if not set(self.acceptable_gses) <= set(self.candidate_gses):
            raise ValueError("Accepted studies must be in the reviewed pool")
        if self.stage == "selection" and set(self.selections) != set(self.acceptable_gses):
            raise ValueError("Selection cases need an answer for each accepted study")
        if self.stage == "discovery" and self.selections:
            raise ValueError("Discovery must not require post-inspection sample explanations")
        return self

    def public_task(self) -> dict:
        return {
            "id": self.id,
            "stage": self.stage,
            "prompt": self.prompt,
            "constraints": self.constraints,
            "candidate_gses": self.candidate_gses,
        }

    def prompt_hash(self) -> str:
        return digest(self.public_task())


class PilotSuite(StrictModel):
    schema_version: int = 1
    id: str = "pancreatic-approved-development-v1"
    data_kind: Literal["real", "synthetic"] = "real"
    input_pack_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    review_manifest_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    cases: list[PilotCase] = Field(min_length=1)
    pending: list[str]

    @model_validator(mode="after")
    def unique_cases(self):
        if len({c.id for c in self.cases}) != len(self.cases):
            raise ValueError("Duplicate pilot case IDs")
        return self


class FieldObservation(StrictModel):
    value: str | None
    evidence: list[Evidence] = Field(default_factory=list)


class PilotRun(StrictModel):
    case_id: str
    stage: Stage
    system: Literal["specialist", "baseline"]
    conditions: Conditions
    run_status: Literal["complete", "error", "timeout"]
    candidate_gses: list[str] = Field(default_factory=list)
    selected_samples: dict[str, list[str]] = Field(default_factory=dict)
    sample_fields: dict[str, dict[str, dict[str, FieldObservation]]] = Field(default_factory=dict)
    disclosures: list[Disclosure] = Field(default_factory=list)
    analysis_readiness: dict[str, Literal["unreviewed", "approved", "blocked"]] = Field(
        default_factory=dict
    )
    elapsed_seconds: float = Field(ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    raw_output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    error: str | None = None


def evidence_exists(item: Evidence, sources: dict) -> bool:
    source = sources.get(item.gse)
    if not source:
        return False
    fields = source.get("samples", {}).get(item.gsm, {}) if item.gsm else source["fields"]
    return item.quote in fields.get(item.field, [])


def score_pilot_case(case: PilotCase, run: PilotRun, suite: PilotSuite, sources: dict) -> dict:
    if run.case_id != case.id or run.stage != case.stage:
        raise ValueError("Observation does not match the case and stage")
    if run.conditions.prompt_sha256 != case.prompt_hash():
        raise ValueError("Observed prompt/stage/constraints differ from the released task")
    if run.conditions.snapshot_sha256 != suite.input_pack_sha256:
        raise ValueError("Observed source pack differs from the release")
    errors: list[str] = []
    incomplete: list[str] = []
    submitted = run.candidate_gses if case.stage == "discovery" else list(run.selected_samples)
    accepted = set(case.acceptable_gses)
    unknown = set(submitted) - set(case.candidate_gses)
    if unknown:
        incomplete.append(f"Unreviewed out-of-pool studies: {sorted(unknown)}")
    rejected = (set(submitted) & set(case.candidate_gses)) - accepted
    if rejected:
        errors.append(
            f"Study does not meet reviewed requirements at this stage: {sorted(rejected)}"
        )
    if len(set(submitted)) != len(submitted):
        errors.append("Duplicate study results")
    maximum = int(case.constraints.get("max_datasets", 20))
    minimum = int(case.constraints.get("min_datasets", 1))
    if len(set(submitted) & accepted) < minimum:
        errors.append("Fewer acceptable studies returned than the task minimum")
    if len(submitted) > maximum:
        errors.append("Exceeded the requested dataset maximum")
    if case.stage == "discovery" and (run.selected_samples or run.sample_fields or run.disclosures):
        incomplete.append("Discovery capture must contain only the discovery-stage response")
    # These reviewed cases establish no positive or negative downstream suitability verdict.
    for gse, readiness in run.analysis_readiness.items():
        if readiness != "unreviewed":
            errors.append(f"Unapproved downstream suitability claim: {gse} ({readiness})")
    field_correct = field_total = evidence_correct = evidence_total = 0
    sample_correct = sample_total = exact_selections = 0
    disclosure_correct = disclosure_total = 0
    observed_disclosures = {}
    for item in run.disclosures:
        key = (item.gse, item.kind)
        if key in observed_disclosures or len(set(item.sample_ids)) != len(item.sample_ids):
            errors.append(f"Duplicate disclosure or sample identities: {key}")
        observed_disclosures[key] = set(item.sample_ids)
    for gse, selected in run.selected_samples.items():
        answer = case.selections.get(gse)
        if answer is None:
            continue
        expected = set(answer.sample_ids)
        actual = set(selected)
        sample_correct += len(expected & actual)
        sample_total += len(expected)
        exact = expected == actual and len(actual) == len(selected)
        exact_selections += int(exact)
        if not exact:
            errors.append(f"Incorrect selected sample identities: {gse}")
        predictions = run.sample_fields.get(gse, {})
        for gsm, fields in answer.fields.items():
            for name, gold in fields.items():
                observed = predictions.get(gsm, {}).get(name)
                field_total += 1
                matches = observed is not None and observed.value in [gold.value, *gold.aliases]
                field_correct += int(matches)
                if not matches:
                    errors.append(f"Missing or incorrect reviewed field: {gse}/{gsm}/{name}")
                elif observed is not None and not any(
                    item in gold.evidence for item in observed.evidence
                ):
                    incomplete.append(
                        f"Supporting quote needs review for this field: {gse}/{gsm}/{name}"
                    )
        for gsm in answer.unresolved_sample_ids:
            value = predictions.get(gsm, {}).get("experimental_model")
            if value is not None and value.value is not None:
                errors.append(f"Unresolved model assignment promoted to fact: {gsm}")
        required = {(item.gse, item.kind): set(item.sample_ids) for item in answer.disclosures}
        disclosure_total += len(required)
        for key, ids in required.items():
            matches = observed_disclosures.get(key) == ids
            disclosure_correct += int(matches)
            if not matches:
                errors.append(f"Missing or incorrect uncertainty/coverage disclosure: {key}")
        if any(key[0] == gse and key not in required for key in observed_disclosures):
            errors.append(f"Unsupported coverage/model disclosure: {gse}")
    for gse, samples in run.sample_fields.items():
        if gse not in run.selected_samples:
            errors.append(f"Sample fields supplied outside a selected study: {gse}")
        source_samples = sources.get(gse, {}).get("samples", {})
        for gsm, fields in samples.items():
            if gsm not in source_samples:
                errors.append(f"Sample absent from source pack: {gsm}")
            for name, observed in fields.items():
                if observed.value is None:
                    continue
                answer = case.selections.get(gse)
                if answer is None or name not in answer.fields.get(gsm, {}):
                    incomplete.append(f"Additional field needs review: {gse}/{gsm}/{name}")
                evidence_total += 1
                valid = bool(observed.evidence) and all(
                    e.gse == gse and e.gsm == gsm and evidence_exists(e, sources)
                    for e in observed.evidence
                )
                evidence_correct += int(valid)
                if not valid:
                    errors.append(f"Missing or invalid source evidence: {gse}/{gsm}/{name}")
    if any(item.gse not in run.selected_samples for item in run.disclosures):
        errors.append("Disclosure supplied outside a selected study")
    if run.run_status != "complete":
        errors.append(f"Run did not complete: {run.run_status}")
    if run.conditions.protocol != "frozen_pool":
        incomplete.append("Live discovery requires a separately reviewed pool and protocol")
    if run.elapsed_seconds > run.conditions.time_budget_seconds:
        incomplete.append("Declared time budget exceeded")
    if run.input_tokens is None or run.output_tokens is None:
        incomplete.append("Token budget compliance unmeasured")
    elif run.input_tokens + run.output_tokens > run.conditions.token_budget:
        incomplete.append("Declared token budget exceeded")
    task_passed = len(set(submitted) & accepted) >= minimum and not errors and not incomplete
    return {
        "case_id": case.id,
        "stage": case.stage,
        "system": run.system,
        "metrics": {
            "returned_precision": ratio(len(set(submitted) & accepted), len(submitted)),
            "acceptable_pool_coverage": ratio(len(set(submitted) & accepted), len(accepted)),
            "sample_recall_selected_studies": ratio(sample_correct, sample_total),
            "exact_sample_selections": ratio(exact_selections, len(run.selected_samples)),
            "field_accuracy": ratio(field_correct, field_total),
            "field_evidence": ratio(evidence_correct, evidence_total),
            "disclosures": ratio(disclosure_correct, disclosure_total),
            "elapsed_seconds": run.elapsed_seconds,
            "cost_usd": run.cost_usd,
        },
        "task_passed": task_passed,
        "errors": sorted(set(errors)),
        "incomplete": incomplete,
        "scientific_score": None,
    }


def compare_pilot(
    suite: PilotSuite,
    sources: dict,
    runs: list[PilotRun],
    *,
    raw_output_hashes: set[str] | None = None,
) -> dict:
    cases = {case.id: case for case in suite.cases}
    indexed = {}
    results = []
    for run in runs:
        key = (run.case_id, run.system)
        if run.case_id not in cases or key in indexed:
            raise ValueError("Unknown case or duplicate case/system attempt")
        indexed[key] = run
        row = score_pilot_case(cases[run.case_id], run, suite, sources)
        if raw_output_hashes is None or run.raw_output_sha256 not in raw_output_hashes:
            row["incomplete"].append("Original response file not supplied or hash differs")
            row["task_passed"] = False
        row["raw_output_sha256"] = run.raw_output_sha256
        row["conditions"] = run.conditions.model_dump()
        row["run_status"] = run.run_status
        row["input_tokens"] = run.input_tokens
        row["output_tokens"] = run.output_tokens
        results.append(row)
    pairing_errors = []
    for case in suite.cases:
        left = indexed.get((case.id, "specialist"))
        right = indexed.get((case.id, "baseline"))
        if left is None or right is None:
            pairing_errors.append(f"{case.id}: missing specialist or baseline")
            continue
        for key in Conditions.model_fields:
            if key != "code_revision" and getattr(left.conditions, key) != getattr(
                right.conditions, key
            ):
                pairing_errors.append(f"{case.id}: unequal {key}")
        if left.conditions.attempt != 1 or right.conditions.attempt != 1:
            pairing_errors.append(f"{case.id}: only preregistered first attempts are supported")
    summary = {}
    for stage in ("discovery", "selection"):
        scheduled = [c for c in suite.cases if c.stage == stage]
        for system in ("specialist", "baseline"):
            rows = [r for r in results if r["stage"] == stage and r["system"] == system]
            summary[f"{stage}/{system}"] = {
                "coverage": ratio(len(rows), len(scheduled)),
                "task_completion": ratio(sum(r["task_passed"] for r in rows), len(scheduled)),
                "cases_with_errors": sum(bool(r["errors"]) for r in rows),
            }
    return {
        "suite": suite.id,
        "scope": "reviewed development selection/discovery only",
        "data_kind": suite.data_kind,
        "input_pack_sha256": suite.input_pack_sha256,
        "review_manifest_sha256": suite.review_manifest_sha256,
        "pairing_errors": pairing_errors,
        "cases": results,
        "summaries": summary,
        "paired_development_ready": suite.data_kind == "real"
        and not pairing_errors
        and bool(results)
        and not any(r["incomplete"] for r in results),
        "scientific_benchmark_ready": False,
        "pending": suite.pending,
        "note": "Optional acceptable studies are not mandatory in every bounded result. "
        "Missing scheduled attempts remain in completion denominators. "
        "No live-search recall, downstream validity or held-out advantage is established.",
    }

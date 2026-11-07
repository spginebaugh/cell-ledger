"""Frozen, independently reviewed gold and provider-neutral observed results."""

from __future__ import annotations

import hashlib
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal["proceed", "ask", "decline", "no_results", "error"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Evidence(StrictModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    gsm: str | None = Field(default=None, pattern=r"^GSM\d+$")
    field: str
    quote: str = Field(min_length=1)


class SourceRecord(StrictModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    exists: bool = True
    url: str
    retrieved_at: str
    fields: dict[str, list[str]] = Field(default_factory=dict)
    samples: dict[str, dict[str, list[str]]] = Field(default_factory=dict)
    absence_evidence: str | None = None

    @model_validator(mode="after")
    def absence_is_explicit(self):
        if not self.exists and not self.absence_evidence:
            raise ValueError(
                "A nonexistent accession needs verified absence evidence, not a timeout"
            )
        return self


class Snapshot(StrictModel):
    schema_version: int = 1
    data_kind: Literal["real", "synthetic"] = "real"
    records: dict[str, SourceRecord]

    @model_validator(mode="after")
    def consistent_ids(self):
        if any(gse != record.gse for gse, record in self.records.items()):
            raise ValueError("Snapshot keys must match source accessions")
        return self

    def contains(self, evidence: Evidence) -> bool:
        source = self.records.get(evidence.gse)
        if not source or not source.exists:
            return False
        fields = source.samples.get(evidence.gsm, {}) if evidence.gsm else source.fields
        return evidence.quote in fields.get(evidence.field, [])

    def digest(self) -> str:
        return digest(self.model_dump())


class SampleGold(StrictModel):
    fields: dict[str, str | None]
    evidence: list[Evidence] = Field(min_length=1)


class StudyGold(StrictModel):
    family_id: str = Field(min_length=1)
    relevant: bool
    eligible: bool
    expected_gsms: list[str] = Field(default_factory=list)
    units: str | None = None
    de_ready: bool | None = None
    samples: dict[str, SampleGold] = Field(default_factory=dict)
    rationale: str = Field(min_length=1)
    evidence: list[Evidence] = Field(default_factory=list)
    reviewed_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def unique_samples(self):
        if len(set(self.expected_gsms)) != len(self.expected_gsms):
            raise ValueError("Duplicate expected GSMs")
        if not set(self.samples) <= set(self.expected_gsms):
            raise ValueError("Scored sample labels must belong to the expected exported samples")
        return self


class CaseGold(StrictModel):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]+$")
    split: Literal["development", "held_out"]
    prompt: str = Field(min_length=3)
    constraints: dict[str, str | int | bool] = Field(default_factory=dict)
    required_workflow: Literal["none", "load_only", "downstream"] = "none"
    expected_action: Literal["proceed", "ask", "decline", "no_results"]
    clarification_targets: list[str] = Field(default_factory=list)
    studies: dict[str, StudyGold] = Field(default_factory=dict)
    reviewed_by: str = Field(min_length=1)
    review_notes: str = Field(min_length=1)

    @model_validator(mode="after")
    def valid_case(self):
        minimum = self.constraints.get("min_datasets", 1)
        maximum = self.constraints.get("max_datasets", 3)
        if (
            type(minimum) is not int
            or type(maximum) is not int
            or not 1 <= minimum <= maximum <= 10
        ):
            raise ValueError("Dataset limits must be integers: 1 <= minimum <= maximum <= 10")
        positives = [s for s in self.studies.values() if s.relevant and s.eligible]
        if self.expected_action == "proceed" and not positives:
            raise ValueError("A proceed case needs at least one relevant eligible study")
        if self.expected_action == "ask" and not self.clarification_targets:
            raise ValueError("Ask cases need a specific missing decision to evaluate")
        if self.expected_action == "no_results" and positives:
            raise ValueError("No-results gold cannot contain relevant eligible studies")
        if self.required_workflow != "none" and any(not s.expected_gsms for s in positives):
            raise ValueError("Workflow cases require expected sample identities for each positive")
        return self


class Benchmark(StrictModel):
    id: str
    version: str
    data_kind: Literal["real", "synthetic"] = "real"
    snapshot_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")
    frozen: bool = False
    cases: list[CaseGold] = Field(min_length=1)

    @model_validator(mode="after")
    def no_leakage(self):
        if len({case.id for case in self.cases}) != len(self.cases):
            raise ValueError("Duplicate case IDs")
        families: dict[str, str] = {}
        accessions: dict[str, tuple[str, str]] = {}
        for case in self.cases:
            for gse, study in case.studies.items():
                previous = accessions.setdefault(gse, (case.split, study.family_id))
                if previous != (case.split, study.family_id):
                    raise ValueError(f"{gse} changes split or family between cases")
                if families.setdefault(study.family_id, case.split) != case.split:
                    raise ValueError(f"Study family {study.family_id} leaks across splits")
        return self

    def validate_sources(self, snapshot: Snapshot) -> None:
        if self.data_kind != snapshot.data_kind:
            raise ValueError("Real and synthetic evaluation material cannot be mixed")
        if self.snapshot_sha256 != snapshot.digest():
            raise ValueError("Source snapshot hash does not match the benchmark")
        for case in self.cases:
            for gse, study in case.studies.items():
                source = snapshot.records.get(gse)
                if source is None:
                    raise ValueError(f"Unverified gold accession: {gse}")
                if self.data_kind == "real" and not source.url.startswith("https://"):
                    raise ValueError("Real benchmark evidence needs an HTTPS source URL")
                if not source.exists and (study.relevant or study.eligible or study.expected_gsms):
                    raise ValueError("A nonexistent study cannot be a positive or export samples")
                if source.exists and not study.evidence:
                    raise ValueError(f"{gse} needs independent source evidence")
                if not set(study.expected_gsms) <= set(source.samples):
                    raise ValueError(f"{gse} gold contains samples absent from the snapshot")
                for evidence in study.evidence:
                    if evidence.gse != gse or not snapshot.contains(evidence):
                        raise ValueError(f"Invalid gold source evidence for {gse}")
                for gsm, sample in study.samples.items():
                    for evidence in sample.evidence:
                        if (
                            evidence.gse != gse
                            or evidence.gsm != gsm
                            or not snapshot.contains(evidence)
                        ):
                            raise ValueError(f"Invalid gold sample evidence for {gsm}")


class Conditions(StrictModel):
    model: str = Field(min_length=1)
    source_access: str = Field(min_length=1)
    execution_access: str = Field(min_length=1)
    time_budget_seconds: int = Field(gt=0)
    token_budget: int = Field(gt=0)
    protocol: Literal["frozen_pool", "live_search"] = "frozen_pool"
    snapshot_sha256: str
    prompt_sha256: str
    attempt: int = Field(default=1, ge=1)
    code_revision: str = Field(min_length=1)


class SamplePrediction(StrictModel):
    gse: str
    gsm: str
    fields: dict[str, str | None]
    evidence: dict[str, Evidence] = Field(default_factory=dict)


class BundleObservation(StrictModel):
    gse: str
    sample_ids: list[str]
    units: str
    de_ready: bool
    integrity_passed: bool
    integrity_errors: list[str] = Field(default_factory=list)
    workflow_executed: bool = False
    workflow_passed: bool | None = None
    workflow_log_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")

    @model_validator(mode="after")
    def execution_is_evidenced(self):
        if self.integrity_passed and self.integrity_errors:
            raise ValueError("An artifact with integrity errors cannot pass inspection")
        if self.workflow_executed and (
            self.workflow_passed is None or not self.workflow_log_sha256
        ):
            raise ValueError("Workflow execution requires a result and log checksum")
        if not self.workflow_executed and self.workflow_passed is not None:
            raise ValueError("Cannot claim a workflow result without execution")
        return self


class RunRecord(StrictModel):
    case_id: str
    system: Literal["specialist", "baseline"]
    conditions: Conditions
    run_status: Literal["complete", "error", "timeout"]
    action: Action
    ranking: list[str]
    recommendations: list[str]
    clarification_targets: list[str] = Field(default_factory=list)
    questions: list[str] = Field(default_factory=list)
    question_reviewed_by: str | None = None
    samples: list[SamplePrediction] = Field(default_factory=list)
    bundles: list[BundleObservation] = Field(default_factory=list)
    elapsed_seconds: float = Field(ge=0)
    cost_usd: float | None = Field(default=None, ge=0)
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    human_corrections: int = Field(default=0, ge=0)
    clarification_answers: int = Field(default=0, ge=0)
    error: str | None = None
    raw_output_sha256: str = Field(pattern=r"^[a-f0-9]{64}$")


def digest(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    ).hexdigest()


def prompt_digest(case: CaseGold) -> str:
    return digest({"prompt": case.prompt, "constraints": case.constraints})

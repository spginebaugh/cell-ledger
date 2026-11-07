"""Gold cases: a prompt, the action the specialist should take, and a reviewed pool of GEO
series with a relevance and eligibility verdict each.

One JSON file per case in ``evals/cases/``. Cases start as ``draft`` and become ``reviewed``
when a named person has checked every pool entry. Scoring never infers gold from a run: a
candidate the pool has no verdict for goes to the review queue, not to a score.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Action = Literal["proceed", "ask", "decline", "no_results"]
"""What the first turn should do.

proceed     list candidates and no clarifying questions
ask         ask at least one clarifying question (candidates may still be listed)
decline     out of scope: GEO human bulk RNA-seq with counts cannot answer it
no_results  in scope, but no candidate exists (nothing in GEO matches)
"""

CASES_DIR = Path(__file__).parent / "cases"


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PoolEntry(Strict):
    """One reviewed series. ``None`` means not judged yet: it neither helps nor hurts a score."""

    relevant: bool | None = Field(
        default=None, description="does this series answer the prompt's comparison?"
    )
    eligible: bool | None = Field(
        default=None,
        description="human bulk RNA-seq with NCBI raw counts (checkable with the GEO client)",
    )
    rationale: str = ""
    evidence: str = Field(default="", description="a quote or file that backs the verdict")
    reviewed_by: str = ""
    source: str = Field(
        default="", description="where the entry came from: query_set, pilot, review_queue, a PMID"
    )

    @property
    def judged(self) -> bool:
        return self.relevant is not None and self.eligible is not None

    @property
    def positive(self) -> bool:
        return self.relevant is True and self.eligible is True


class Case(Strict):
    id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]*$")
    prompt: str = Field(min_length=3)
    expected_action: Action
    clarification_targets: list[list[str]] = Field(
        default_factory=list,
        description="for ask cases: one inner list per decision the question must raise, "
        "each a set of words any of which marks the question as raising it",
    )
    answers: list[str] = Field(
        default_factory=list,
        description="scripted answers for the second turn when the system asks",
    )
    expected_action_after_answers: Action | None = Field(
        default=None, description="what the second turn should do; proceed when unset"
    )
    pool: dict[str, PoolEntry] = Field(default_factory=dict)
    status: Literal["draft", "reviewed"] = "draft"
    reviewed_by: str = ""
    notes: str = ""
    tags: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def consistent(self) -> Case:
        bad = [g for g in self.pool if not g.startswith("GSE") or not g[3:].isdigit()]
        if bad:
            raise ValueError(f"{self.id}: pool keys must be GSE accessions, not {bad}")
        if self.expected_action == "ask" and not self.clarification_targets:
            raise ValueError(f"{self.id}: an ask case needs clarification_targets")
        if any(
            not words or any(not w.strip() for w in words) for words in self.clarification_targets
        ):
            raise ValueError(f"{self.id}: every clarification target needs non-empty words")
        if self.expected_action != "ask" and self.answers:
            raise ValueError(f"{self.id}: answers only apply to ask cases")
        if self.expected_action in {"decline", "no_results"} and self.positives():
            raise ValueError(f"{self.id}: a {self.expected_action} case cannot have positives")
        if self.status == "reviewed":
            if not self.reviewed_by:
                raise ValueError(f"{self.id}: a reviewed case names its reviewer")
            if self.expected_action == "proceed" and not self.positives():
                raise ValueError(f"{self.id}: a reviewed proceed case needs a positive")
            unjudged = [g for g, e in self.pool.items() if not e.judged]
            if unjudged:
                raise ValueError(f"{self.id}: reviewed case has unjudged pool entries {unjudged}")
        return self

    def positives(self) -> set[str]:
        return {g for g, e in self.pool.items() if e.positive}

    def judged(self) -> dict[str, PoolEntry]:
        return {g: e for g, e in self.pool.items() if e.judged}

    @property
    def second_turn_action(self) -> Action:
        return self.expected_action_after_answers or "proceed"

    def digest(self) -> str:
        """Identity of what the system is asked: prompt and scripted answers only."""
        payload = {"prompt": self.prompt, "answers": self.answers}
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


class Suite(Strict):
    cases: list[Case]

    @model_validator(mode="after")
    def unique(self) -> Suite:
        ids = [c.id for c in self.cases]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate case ids")
        return self

    def by_id(self) -> dict[str, Case]:
        return {c.id: c for c in self.cases}

    def digest(self) -> str:
        return hashlib.sha256(
            json.dumps([c.model_dump() for c in self.cases], sort_keys=True).encode()
        ).hexdigest()


def load_suite(directory: Path = CASES_DIR) -> Suite:
    """Every ``*.json`` in the directory is one case; the file name must equal the id."""
    cases = []
    for path in sorted(directory.glob("*.json")):
        case = Case.model_validate_json(path.read_text())
        if case.id != path.stem:
            raise ValueError(f"{path.name}: file name must match case id {case.id!r}")
        cases.append(case)
    if not cases:
        raise ValueError(f"no case files in {directory}")
    return Suite(cases=cases)


def write_case(case: Case, directory: Path = CASES_DIR) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{case.id}.json"
    path.write_text(json.dumps(case.model_dump(), indent=2, ensure_ascii=False) + "\n")
    return path

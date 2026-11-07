"""What one run of one case produced, in a shape both systems share.

A record is written straight after the run and never edited. Scoring reads records and
cases; it does not re-run anything.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

System = Literal["specialist", "baseline"]
TurnAction = Literal["proceed", "ask", "decline", "no_results", "error"]


class Conditions(BaseModel):
    """Everything about a run that is not the case itself; paired runs must agree on all of it
    except ``fingerprint``, which is the point of the comparison."""

    model_config = ConfigDict(extra="forbid")

    system: System
    model: str
    effort: str
    fingerprint: str = Field(
        description="hash of the system's prompt and tools; see Agent.fingerprint"
    )
    web_search: bool = Field(description="specialist: Exa configured; baseline: web search tool on")
    code_revision: str
    dirty: bool
    geo_cache: str = Field(description="GEO response cache the run used, for exact reruns")
    case_sha256: str
    suite_sha256: str
    run_id: str
    started_at: str


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answers: list[str] = Field(default_factory=list)
    action: TurnAction
    output: dict[str, Any] | None = Field(
        default=None, description="the DiscoveryResult (specialist) or DiscoveryOutput (baseline)"
    )
    elapsed_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    web_search_requests: int = 0
    error: str | None = None


class Verification(BaseModel):
    """The final candidates checked against GEO by code, after the run. Both systems get it;
    for the specialist it is a regression check, for the baseline it is the headline."""

    model_config = ConfigDict(extra="forbid")

    eligible: list[str] = Field(default_factory=list)
    exists_only: list[str] = Field(
        default_factory=list, description="in GEO, but not human bulk RNA-seq with counts"
    )
    missing: list[str] = Field(default_factory=list, description="not in GEO at all")
    invalid: list[str] = Field(default_factory=list, description="not even a GSE accession")


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str
    system: System
    repeat: int = Field(ge=1)
    conditions: Conditions
    turns: list[Turn] = Field(min_length=1)
    final_action: TurnAction
    candidates: list[str] = Field(default_factory=list, description="final turn, in order")
    candidate_details: dict[str, dict[str, Any]] = Field(
        default_factory=dict, description="gse -> title/why/hints, for the review queue"
    )
    rejected: list[str] = Field(default_factory=list)
    questions: list[dict[str, Any]] = Field(default_factory=list, description="first turn's")
    out_of_scope: str | None = None
    seen: list[str] = Field(
        default_factory=list,
        description="specialist: every accession GEO returned across turns; baseline: empty",
    )
    per_query: dict[str, list[str]] = Field(
        default_factory=dict, description="specialist: GEO query -> accessions it returned"
    )
    invented: list[str] = Field(
        default_factory=list, description="specialist: accessions named but never confirmed"
    )
    verification: Verification = Field(default_factory=Verification)
    elapsed_seconds: float = 0.0
    input_tokens: int = 0
    output_tokens: int = 0
    web_search_requests: int = 0
    error: str | None = None

    def save(self, root: Path) -> Path:
        path = root / self.system / self.case_id / f"r{self.repeat}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2) + "\n")
        return path


def derive_action(output: dict[str, Any] | None) -> TurnAction:
    """The action a DiscoveryOutput-shaped result amounts to. Asking wins over listing."""
    if output is None:
        return "error"
    if output.get("out_of_scope"):
        return "decline"
    if output.get("clarifying_questions"):
        return "ask"
    if output.get("candidates"):
        return "proceed"
    return "no_results"


def git_revision(root: Path) -> tuple[str, bool]:
    try:
        rev = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
        dirty = bool(
            subprocess.check_output(["git", "status", "--porcelain"], cwd=root, text=True).strip()
        )
    except (OSError, subprocess.CalledProcessError):
        return "unknown", True
    return rev, dirty


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def load_records(run_dir: Path) -> list[RunRecord]:
    return [
        RunRecord.model_validate_json(p.read_text())
        for p in sorted(run_dir.glob("*/*/r*.json"))
        if p.parent.parent.name in ("specialist", "baseline")
    ]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")

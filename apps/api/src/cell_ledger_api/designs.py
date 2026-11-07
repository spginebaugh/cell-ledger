"""The design that goes into a run, and the agent's proposal that wraps it.

These live apart from ``runs.py`` and ``agent/design.py`` because a dataset row carries its
proposal (``sessions.py``) while the run service carries its design: both need the models,
neither should import the other.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from cell_ledger.report.models import MarkerExpectation
from cell_ledger.samplesheet import Contrast, SampleSheet


class RunRequest(BaseModel):
    """One design file, as ``cell-ledger run --design`` reads it, plus a few run options."""

    samplesheet: SampleSheet
    contrasts: list[Contrast] = Field(min_length=1)
    markers: list[MarkerExpectation] = Field(default_factory=list)
    genes: list[str] = Field(default_factory=list, description="symbols or GeneIDs to look up")
    enrichment: bool = True
    figures: bool = True


class DesignProposal(BaseModel):
    """The one contrast the agent chose for a dataset, with every reason to hesitate attached.
    Nobody confirms it: ``problems`` empty means it runs, otherwise the dataset is skipped."""

    design: RunRequest
    problems: list[str] = Field(
        default_factory=list, description="why the contrast must not run; empty when runnable"
    )
    qualifications: list[str] = Field(
        default_factory=list, description="caveats that travel with the result"
    )
    decisions: list[str] = Field(
        default_factory=list, description="choices the record left open and how they were made"
    )
    notes: str = ""
    validation_errors: list[str] = Field(
        default_factory=list, description="labels Claude could not back with evidence"
    )
    attempts: int = 1

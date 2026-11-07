from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field


class Blocker(StrEnum):
    NO_RAW_COUNTS = "no_raw_counts"
    UNREADABLE_FORMAT = "unreadable_format"
    AMBIGUOUS_LABELS = "ambiguous_labels"
    TOO_FEW_SAMPLES = "too_few_samples"


class UsabilityVerdict(BaseModel):
    gse: str
    usable: bool
    blockers: list[Blocker] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)

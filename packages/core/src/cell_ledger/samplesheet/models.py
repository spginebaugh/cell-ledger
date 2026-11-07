"""The sample sheet is the single contract between GEO metadata, analysis and the UI.

Upstream (search, fetch, harmonize) produces a ``SampleSheet`` per GEO series.
Downstream (QC, differential expression, report) reads only the typed fields.
Every LLM-filled field must be backed by ``evidence``: verbatim strings copied
from the GEO record. When ``raw`` is populated the model refuses evidence that
does not appear in the record, so hallucinated labels cannot be constructed.
"""

from __future__ import annotations

from collections import Counter
from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, Field, model_validator

REVIEW_CONFIDENCE_THRESHOLD = 0.7


class Assay(StrEnum):
    BULK = "bulk"
    SINGLE_CELL = "single_cell"


class Group(StrEnum):
    """Role of a sample relative to the research question."""

    CASE = "case"
    CONTROL = "control"
    OTHER = "other"
    UNKNOWN = "unknown"


class Sample(BaseModel):
    """One GEO sample (GSM) with harmonized labels.

    ``raw`` holds the GEO ``characteristics_ch1`` lines as ``{key: value}``;
    ``title`` and ``source_name`` are copied from GEO as-is. Those three are the
    only places an ``evidence`` string may come from.
    """

    gsm: str = Field(pattern=r"^GSM\d+$")
    title: str
    source_name: str | None = None

    group: Group = Group.UNKNOWN
    condition: str | None = None
    treatment: str | None = None
    dose: str | None = None
    time_point: str | None = None
    tissue: str | None = None
    cell_type: str | None = None
    cell_line: str | None = None
    genotype: str | None = None
    sex: str | None = None
    age: str | None = None
    donor: str | None = None
    batch: str | None = None
    organism: str | None = None
    replicate: int | None = None

    evidence: list[str] = Field(default_factory=list)
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    needs_review: bool = False
    raw: dict[str, str] = Field(default_factory=dict)

    def record_strings(self) -> list[str]:
        """Every verbatim string from the GEO record that evidence may cite."""
        out = [self.title]
        if self.source_name:
            out.append(self.source_name)
        out.extend(f"{k}: {v}" for k, v in self.raw.items())
        return out

    @model_validator(mode="after")
    def _evidence_must_appear_in_record(self) -> Sample:
        if self.raw and self.evidence:
            haystack = self.record_strings()
            bad = [e for e in self.evidence if not any(e in h for h in haystack)]
            if bad:
                raise ValueError(f"{self.gsm}: evidence not found in GEO record: {bad!r}")
        return self

    @model_validator(mode="after")
    def _low_confidence_needs_review(self) -> Sample:
        if self.confidence is not None and self.confidence < REVIEW_CONFIDENCE_THRESHOLD:
            self.needs_review = True
        return self


class SampleSheet(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    assay: Assay
    title: str | None = None
    samples: list[Sample] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_gsm(self) -> SampleSheet:
        seen = [s.gsm for s in self.samples]
        if len(seen) != len(set(seen)):
            raise ValueError("duplicate GSM accessions in sample sheet")
        return self

    @property
    def gsms(self) -> list[str]:
        return [s.gsm for s in self.samples]

    def by_gsm(self, gsm: str) -> Sample:
        for s in self.samples:
            if s.gsm == gsm:
                return s
        raise KeyError(gsm)

    def group_counts(self) -> dict[Group, int]:
        return dict(Counter(s.group for s in self.samples))

    def subset(self, gsms: list[str]) -> SampleSheet:
        """A new sheet with only ``gsms`` (order preserved from this sheet)."""
        keep = set(gsms)
        return self.model_copy(update={"samples": [s for s in self.samples if s.gsm in keep]})

    def to_dataframe(self) -> pd.DataFrame:
        """Flat per-sample table indexed by GSM, as analysis steps expect.

        ``raw`` is dropped; ``evidence`` is joined with `` | `` so the frame is
        writable as CSV.
        """
        rows = []
        for s in self.samples:
            row = s.model_dump(exclude={"raw", "evidence"}, mode="json")
            row["evidence"] = " | ".join(s.evidence)
            rows.append(row)
        return pd.DataFrame(rows).set_index("gsm")

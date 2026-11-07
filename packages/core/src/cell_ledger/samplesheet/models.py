"""The sample sheet is the single contract between GEO metadata, analysis and the UI."""

from __future__ import annotations

from enum import StrEnum

import pandas as pd
from pydantic import BaseModel, Field, model_validator


class Assay(StrEnum):
    BULK = "bulk"
    SINGLE_CELL = "single_cell"


class Sample(BaseModel):
    """One GEO sample (GSM) with harmonized labels.

    Free-text GEO characteristics land in ``raw``; the typed fields are what the
    analysis steps are allowed to read.
    """

    gsm: str = Field(pattern=r"^GSM\d+$")
    title: str
    condition: str | None = None
    cell_type: str | None = None
    tissue: str | None = None
    organism: str | None = None
    raw: dict[str, str] = Field(default_factory=dict)


class SampleSheet(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    assay: Assay
    samples: list[Sample] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_gsm(self) -> SampleSheet:
        seen = [s.gsm for s in self.samples]
        if len(seen) != len(set(seen)):
            raise ValueError("duplicate GSM accessions in sample sheet")
        return self

    def to_dataframe(self) -> pd.DataFrame:
        """Flat per-sample table indexed by GSM, as analysis steps expect."""
        rows = [s.model_dump(exclude={"raw"}) for s in self.samples]
        return pd.DataFrame(rows).set_index("gsm")

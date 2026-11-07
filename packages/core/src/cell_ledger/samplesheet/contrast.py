"""A two-group comparison over one sample sheet.

The contrast names the GSMs explicitly instead of relying on ``Sample.group``
alone, so a sheet can carry descriptive labels for every sample while the
contrast pins down exactly which samples are compared. Downstream fits
``~ group`` on the union of ``case_gsms`` and ``control_gsms`` and nothing else.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from cell_ledger.samplesheet.models import REVIEW_CONFIDENCE_THRESHOLD, Group, SampleSheet

DEFAULT_MIN_PER_GROUP = 3


class ContrastStatus(StrEnum):
    PROPOSED = "proposed"  # LLM proposal, not yet checked
    CONFIRMED = "confirmed"  # checked against the sheet, or hand-curated
    UNCERTAIN = "uncertain"  # kept, but low confidence or unknown groups nearby
    BLOCKED = "blocked"  # must not be run; see ``rationale``


class Contrast(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    name: str = Field(pattern=r"^[a-z0-9]+(_[a-z0-9]+)*$", description="slug, e.g. ipf_vs_control")
    case_label: str
    control_label: str
    case_gsms: list[str] = Field(min_length=1)
    control_gsms: list[str] = Field(min_length=1)
    blocking: str | None = Field(
        default=None,
        description="Sample field pairing case and control (e.g. 'donor'); recorded, not modelled",
    )
    restricted_to: dict[str, str] = Field(
        default_factory=dict,
        description="Sample field -> value the contrast is limited to, e.g. {'time_point': '24 h'}",
    )
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    status: ContrastStatus = ContrastStatus.PROPOSED
    rationale: str = ""

    @model_validator(mode="after")
    def _disjoint_and_unique(self) -> Contrast:
        case, ctrl = set(self.case_gsms), set(self.control_gsms)
        if len(case) != len(self.case_gsms) or len(ctrl) != len(self.control_gsms):
            raise ValueError("duplicate GSM within a contrast arm")
        if case & ctrl:
            raise ValueError(f"GSMs in both arms: {sorted(case & ctrl)}")
        return self

    @property
    def gsms(self) -> list[str]:
        return [*self.case_gsms, *self.control_gsms]

    def qualifications(
        self, sheet: SampleSheet, *, min_confidence: float = REVIEW_CONFIDENCE_THRESHOLD
    ) -> list[str]:
        """Reasons to qualify, not block, a result: uncertain status, low confidence, review."""
        out: list[str] = []
        if self.status == ContrastStatus.UNCERTAIN:
            out.append(f"contrast marked uncertain: {self.rationale or 'no reason given'}")
        if self.confidence is not None and self.confidence < min_confidence:
            out.append(f"contrast confidence {self.confidence:.2f} < {min_confidence}")
        known = set(sheet.gsms)
        samples = [sheet.by_gsm(g) for g in self.gsms if g in known]
        review = [s.gsm for s in samples if s.needs_review]
        if review:
            out.append(f"{len(review)} contrast samples need review: {review}")
        scores = [s.confidence for s in samples if s.confidence is not None]
        if scores and sum(scores) / len(scores) < min_confidence:
            out.append(f"mean label confidence {sum(scores) / len(scores):.2f} < {min_confidence}")
        return out

    def arm_of(self, gsm: str) -> Group:
        if gsm in self.case_gsms:
            return Group.CASE
        if gsm in self.control_gsms:
            return Group.CONTROL
        raise KeyError(gsm)

    def problems(
        self, sheet: SampleSheet, *, min_per_group: int = DEFAULT_MIN_PER_GROUP
    ) -> list[str]:
        """Reasons this contrast must not be run against ``sheet``. Empty means DE-ready."""
        out: list[str] = []
        if sheet.gse != self.gse:
            out.append(f"contrast is for {self.gse} but sheet is {sheet.gse}")
        known = set(sheet.gsms)
        missing = [g for g in self.gsms if g not in known]
        if missing:
            out.append(f"GSMs not in sample sheet: {missing}")
        for g in self.gsms:
            if g not in known:
                continue
            label = sheet.by_gsm(g).group
            if label not in (self.arm_of(g), Group.OTHER):
                out.append(f"{g} is in the {self.arm_of(g)} arm but labelled {label}")
        if len(self.case_gsms) < min_per_group or len(self.control_gsms) < min_per_group:
            out.append(
                f"fewer than {min_per_group} samples per group "
                f"({len(self.case_gsms)} case, {len(self.control_gsms)} control)"
            )
        if self.status == ContrastStatus.BLOCKED:
            out.append(f"contrast is blocked: {self.rationale or 'no reason given'}")
        if self.status == ContrastStatus.PROPOSED:
            out.append("contrast is only proposed; it must be confirmed against the sheet first")
        for field, value in self.restricted_to.items():
            off = [
                g
                for g in self.gsms
                if g in known and getattr(sheet.by_gsm(g), field, None) != value
            ]
            if off:
                out.append(f"restricted to {field}={value!r} but these differ: {off}")
        return out

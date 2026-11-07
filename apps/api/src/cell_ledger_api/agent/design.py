"""The design step: for one collected series, Claude labels each sample from its GEO record and
chooses the one two-group contrast that answers the question.

:func:`compile_design` turns the labels into a :class:`SampleSheet`, whose validator refuses
any label that is not backed by a verbatim quote from the GEO record, and checks the contrast
with ``Contrast.problems``. Validation errors go back to Claude once. Nobody confirms the
result: a contrast without problems runs, one with problems sets the dataset aside, and every
choice Claude made is recorded in ``decisions`` for the result page.
"""

from __future__ import annotations

import json
import re
from typing import Literal

from anthropic.lib._parse._transform import transform_schema
from anthropic.types.beta import BetaMessageParam
from pydantic import BaseModel, Field, ValidationError

from cell_ledger.geo import DatasetRecord, SampleRecord
from cell_ledger.samplesheet import Assay, Contrast, ContrastStatus, Group, Sample, SampleSheet
from cell_ledger_api.agent.llm import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    NOT_CONFIGURED,
    AgentUnavailable,
    Emit,
    TurnRunner,
    final_text,
    reject_refusal,
    request_params,
)
from cell_ledger_api.designs import DesignProposal, RunRequest

MAX_ATTEMPTS = 2
# A design labels every sample with quoted evidence, so its JSON grows with the series;
# thinking shares this budget. Streaming keeps a long response within request timeouts.
DESIGN_MAX_TOKENS = 64000
"""The first answer, and one more after the validator's errors are shown to Claude."""


class DatasetNotReady(LookupError):
    pass


# ----------------------------------------------------------------------------- models


class DesignRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    context: str | None = Field(
        default=None,
        description="what discovery settled: the question as a two-group comparison and the "
        "user's answers to clarifying questions",
    )
    genes: list[str] = Field(default_factory=list)


GroupName = Literal["case", "control", "other", "unknown"]


class SampleLabel(BaseModel):
    gsm: str
    group: GroupName
    condition: str | None = None
    treatment: str | None = None
    tissue: str | None = None
    cell_type: str | None = None
    donor: str | None = None
    time_point: str | None = None
    sex: str | None = None
    age: str | None = None
    batch: str | None = None
    evidence: list[str] = Field(
        description="verbatim substrings of the sample's title, source name or characteristics "
        "that justify the group; required unless group is unknown"
    )
    confidence: float = Field(ge=0.0, le=1.0)


class ContrastProposal(BaseModel):
    name: str = Field(description="slug such as lesional_vs_healthy")
    case_label: str
    control_label: str
    case_gsms: list[str]
    control_gsms: list[str]
    # The pipeline pairs on a sample-sheet column, and "donor" is the only one that identifies
    # a person; any other value would be silently fitted unpaired, so the schema allows no other.
    blocking: Literal["donor"] | None = Field(
        default=None,
        description="donor when the same donors (patients) give samples to both arms, with each "
        "sample's donor field set to its patient or donor id; null otherwise",
    )
    rationale: str
    confidence: float = Field(ge=0.0, le=1.0)


class DesignOutput(BaseModel):
    """What Claude returns; compiled into a SampleSheet and one Contrast by code."""

    samples: list[SampleLabel]
    contrast: ContrastProposal = Field(description="the one comparison that answers the question")
    decisions: list[str] = Field(
        default_factory=list,
        description="each choice the record left open, how it was made and what was rejected",
    )
    notes: str = ""


transform_schema(DesignOutput)  # fail at import if the schema cannot be made strict


# ----------------------------------------------------------------------------- prompt


SYSTEM_DESIGN = """\
You are cell-ledger, a specialist that harmonizes GEO sample metadata into a typed sample
sheet and chooses the one two-group contrast that answers a biologist's question. Nobody
reviews your output before it runs, so decide, and write down what you decided.

Every label you assign must be backed by evidence copied verbatim from that sample's own GEO
record (its title, source name, or one of its characteristics lines). Labels without a
verbatim quote are rejected by the validator, so quote exactly, including case and punctuation.

For each sample in the record:
- group: case if it belongs to the case arm of the question, control for the control arm,
  other for samples that are neither (different disease, treated arm, other tissue), unknown
  when the record does not say.
- fill condition, treatment, tissue, cell_type, donor, time_point, sex, age, batch when the
  record states them; leave them null otherwise. Values may be normalized (e.g. "F" ->
  "female"), but evidence must be verbatim.
- evidence: one or more verbatim substrings supporting the group label.
- confidence: how sure you are of the group label (1.0 only when the record is explicit).

Then choose exactly one contrast: the comparison that answers the question as asked, and as
restated in the context when one is given. Return a slug name, human labels for both arms,
the GSMs in each arm (only samples you labelled case or control and that are in the counts
matrix), blocking "donor" when case and control come from the same donors (and then the
same patient id in each paired sample's donor field), a short rationale, and a confidence.
Prefer the cleanest reading: the untreated or healthy control over other arms, one time
point over pooled ones when pooling would mix effects, and the largest arms
that stay homogeneous. Each arm needs at least three samples; if the series cannot give
that, still return the best contrast and say so in decisions (it will be set aside).

Do not ask questions; there is no one to answer them. Where the record leaves a real choice
(which control to use, whether to pool time points, whether treated samples count), make it
and record it as one line in decisions, naming the alternative you rejected.
"""


def usable_samples(record: DatasetRecord) -> list[SampleRecord]:
    """The samples a design may use: in the counts matrix and with no exclusions. Claude is
    shown only these (:func:`record_text`) and the validator accepts only these
    (:func:`compile_design`), so the two cannot drift apart."""
    return [s for s in record.samples if s.in_counts and not s.exclusions]


def _excluded_because(sample: SampleRecord) -> str:
    return ", ".join(str(e) for e in sample.exclusions) or "not_in_counts"


def record_text(record: DatasetRecord) -> str:
    """The GEO record as Claude sees it: only the :func:`usable_samples`."""
    rows = [
        {
            "gsm": s.gsm,
            "title": s.title,
            "source_name": s.source_name,
            "characteristics": s.characteristics,
        }
        for s in usable_samples(record)
    ]
    doc = {
        "gse": record.gse,
        "title": record.title,
        "summary": record.summary[:3000],
        "overall_design": record.overall_design[:2000],
        "n_samples_with_counts": len(rows),
        "samples": rows,
    }
    return json.dumps(doc, ensure_ascii=False, indent=1)


def design_prompt(record: DatasetRecord, req: DesignRequest) -> str:
    prompt = f"Question: {req.question}\n"
    if req.context:
        prompt += f"Context from the dataset search:\n{req.context}\n"
    if req.genes:
        prompt += f"Genes of interest: {', '.join(req.genes)}\n"
    return prompt + "\nGEO record (only samples that have counts):\n" + record_text(record)


def retry_prompt(errors: list[str]) -> str:
    return (
        "The validator rejected these labels. Fix them by quoting the record verbatim (or set "
        "group to unknown with empty evidence), leave out any sample it says is excluded, and "
        "return the whole design again:\n- " + "\n- ".join(errors[:40])
    )


# ---------------------------------------------------------------------------- compile


def compile_design(
    record: DatasetRecord, out: DesignOutput, genes: list[str]
) -> tuple[DesignProposal | None, list[str]]:
    """Turn Claude's labels into a validated design; returns (proposal, errors).

    A label for a sample outside :func:`usable_samples` is an error and the sample stays out
    of the sheet, so a contrast that still names it has a problem and does not run."""
    by_gsm = {s.gsm: s for s in record.samples}
    usable = {s.gsm for s in usable_samples(record)}
    errors: list[str] = []
    samples: list[Sample] = []
    for lab in out.samples:
        rec = by_gsm.get(lab.gsm)
        if rec is None:
            errors.append(f"{lab.gsm}: not a sample of {record.gse}")
            continue
        if lab.gsm not in usable:
            errors.append(f"{lab.gsm}: excluded from analysis ({_excluded_because(rec)})")
            continue
        raw: dict[str, str] = {}
        for line in rec.characteristics:
            key, sep, value = line.partition(":")
            if sep:
                raw[key.strip()] = value.strip()
        try:
            samples.append(
                Sample(
                    gsm=lab.gsm,
                    title=rec.title,
                    source_name=rec.source_name or None,
                    group=Group(lab.group),
                    condition=lab.condition,
                    treatment=lab.treatment,
                    tissue=lab.tissue,
                    cell_type=lab.cell_type,
                    donor=lab.donor or record_donor(raw),
                    time_point=lab.time_point,
                    sex=lab.sex,
                    age=lab.age,
                    batch=lab.batch,
                    organism=rec.organism or None,
                    evidence=[e for e in lab.evidence if e.strip()],
                    confidence=lab.confidence,
                    raw=raw,
                    raw_lines=list(rec.characteristics),
                )
            )
        except ValidationError as e:
            errors.extend(f"{lab.gsm}: {err['msg']}" for err in e.errors())
    if not samples:
        errors.append("no sample could be labelled")
        return None, errors
    try:
        sheet = SampleSheet(
            gse=record.gse, assay=Assay.BULK, title=record.title or None, samples=samples
        )
    except ValidationError as e:
        errors.extend(err["msg"] for err in e.errors())
        return None, errors
    c = out.contrast
    decisions = list(out.decisions)
    blocking = c.blocking
    paired = paired_donors(samples, c.case_gsms, c.control_gsms)
    if blocking is None and len(paired) >= MIN_PAIRS:
        blocking = "donor"
        decisions.append(
            f"Paired by donor: {len(paired)} donors give samples to both arms, so the fit is "
            "blocked on donor (set by code; an unpaired fit was rejected)."
        )
    try:
        # Confirmed, not proposed: the pipeline runs what passes ``problems`` with no one in
        # between, and the result page shows the decisions instead of a confirm button.
        contrast = Contrast(
            gse=record.gse,
            name=_slug(c.name),
            case_label=c.case_label,
            control_label=c.control_label,
            case_gsms=c.case_gsms,
            control_gsms=c.control_gsms,
            blocking=blocking,
            confidence=c.confidence,
            status=ContrastStatus.CONFIRMED,
            rationale=c.rationale,
        )
    except ValidationError as e:
        errors.extend(f"contrast {c.name}: {err['msg']}" for err in e.errors())
        return None, errors
    design = RunRequest(samplesheet=sheet, contrasts=[contrast], genes=list(dict.fromkeys(genes)))
    return (
        DesignProposal(
            design=design,
            problems=contrast.problems(sheet),
            qualifications=contrast.qualifications(sheet),
            decisions=decisions,
            notes=out.notes,
        ),
        errors,
    )


DONOR_FIELDS = frozenset(
    {
        "patient",
        "patient id",
        "patient no",
        "donor",
        "donor id",
        "individual",
        "individual id",
        "subject",
        "subject id",
    }
)
"""Characteristic names (lowercased, punctuation as spaces) that hold a patient identifier.
Exact names only: "patient's condition" is a diagnosis, not an id."""


def record_donor(raw: dict[str, str]) -> str | None:
    """The patient or donor id the GEO record states for a sample, if it states one. Used when
    Claude leaves the donor field empty, so pairing does not depend on the model filling it."""
    for key, value in raw.items():
        name = " ".join(re.sub(r"[^a-z0-9]+", " ", key.lower()).split())
        if name in DONOR_FIELDS and value.strip():
            return value.strip()
    return None


MIN_PAIRS = 3
"""Donors with samples in both arms needed before code turns on a paired fit by itself."""


def paired_donors(samples: list[Sample], case: list[str], control: list[str]) -> set[str]:
    """Donors (from each sample's donor field) that appear in both arms of the contrast."""
    donor = {s.gsm: (s.donor or "").strip() for s in samples}
    in_case = {donor[g] for g in case if donor.get(g)}
    in_control = {donor[g] for g in control if donor.get(g)}
    return in_case & in_control


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return s or "contrast"


# ------------------------------------------------------------------------------- step


class Designer:
    def __init__(
        self,
        *,
        turn: TurnRunner | None = None,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
    ) -> None:
        self._turn = turn
        self._model = model
        self._effort = effort

    @property
    def available(self) -> bool:
        return self._turn is not None

    async def design(self, record: DatasetRecord, req: DesignRequest, emit: Emit) -> DesignProposal:
        if self._turn is None:
            raise AgentUnavailable(NOT_CONFIGURED)
        if record.status != "ready":
            raise DatasetNotReady(f"{record.gse} is {record.status}")
        messages: list[BetaMessageParam] = [{"role": "user", "content": design_prompt(record, req)}]
        params = request_params(
            model=self._model,
            effort=self._effort,
            system=SYSTEM_DESIGN,
            output=DesignOutput,
            max_tokens=DESIGN_MAX_TOKENS,
        )
        proposal: DesignProposal | None = None  # the latest answer that compiled
        errors: list[str] = []
        unreadable = False
        attempt = 0
        for attempt in range(1, MAX_ATTEMPTS + 1):
            message = await self._turn({**params, "messages": messages}, emit)
            reject_refusal(message)
            if message.stop_reason == "max_tokens":
                errors = [
                    f"the design was cut off at {DESIGN_MAX_TOKENS} tokens "
                    f"({len(record.samples)} samples)"
                ]
                unreadable = True
                break
            try:
                out = DesignOutput.model_validate_json(final_text(message))
            except ValidationError as e:
                errors, unreadable = [f"unreadable output: {e}"], True
                break
            compiled, errors = compile_design(record, out, req.genes)
            if compiled is not None:
                compiled.attempts = attempt
                compiled.validation_errors = errors
                proposal = compiled
            if not errors or attempt == MAX_ATTEMPTS:
                break
            await emit(
                {
                    "type": "tool",
                    "name": "validate",
                    "input": {},
                    "summary": f"{len(errors)} labels rejected; asking Claude to fix them",
                }
            )
            messages.append({"role": "assistant", "content": message.content})
            messages.append({"role": "user", "content": retry_prompt(errors)})
        if proposal is None:
            raise AgentUnavailable("could not build a valid design: " + "; ".join(errors[:5]))
        if proposal.attempts < attempt:
            # The correction was unusable. The earlier design passed the same gates any design
            # does, so it is kept rather than failing the dataset, and the record says so.
            reason = (
                "it was unreadable"
                if unreadable
                else "it did not compile: " + "; ".join(errors[:3])
            )
            proposal.qualifications.append(
                f"Claude's corrected design (attempt {attempt}) was not used because {reason}; "
                f"this is attempt {proposal.attempts}'s design, with "
                f"{len(proposal.validation_errors)} label(s) rejected"
            )
            proposal.attempts = attempt
        return proposal

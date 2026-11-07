"""Sample-level selection: how Claude reads a series' samples, and how its choice of samples
is turned into exact GSM lists by code.

Claude never lists GSMs by hand. It sees every sample field with its distinct values
(:func:`series_digest`) and writes :class:`Rule` s over those values; :func:`select_samples`
applies the rules to every sample, so the same value always lands in the same arm, a value
that is not in the record matches nothing, and every selected sample's evidence is the
verbatim field value the rule names.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Sequence

from pydantic import BaseModel, Field

from cell_ledger.geo import GeoSample, GeoSeries

MIN_PER_ARM = 3
"""The pipeline's contrast needs at least this many samples with counts per arm."""

SERIES_FIELD = "series"
"""A condition on this field holds for every sample when its text is in the series summary
or overall design: for facts the series states about all of its samples."""

_SHOWN_VALUES = 40
_SHOWN_TITLES = 80
_VALUE_CHARS = 240
_NUMBER = re.compile(r"-?\d+(?:\.\d+)?")


# ------------------------------------------------------------------------------ fields


def sample_fields(s: GeoSample) -> dict[str, str]:
    """Every field a rule may name, with its verbatim value. Characteristic keys are as GEO
    has them (a repeated key gets ``.2``); empty fields are left out."""
    fields = {
        "title": s.title,
        "source_name": s.source_name,
        **s.characteristics_dict(),
        "description": s.description,
        "molecule": s.molecule,
        "library_source": s.library_source,
        "growth_protocol": s.growth_protocol,
        "treatment_protocol": s.treatment_protocol,
        "extract_protocol": s.extract_protocol,
    }
    return {k: v for k, v in fields.items() if v}


def _number(value: str) -> float | None:
    m = _NUMBER.search(value)
    return float(m.group()) if m else None


def _quote(value: str) -> str:
    v = value if len(value) <= _VALUE_CHARS else value[:_VALUE_CHARS] + "…"
    return '"' + v.replace('"', "'") + '"'


def series_digest(series: GeoSeries, columns: Sequence[str] | None = None) -> str:
    """The series as Claude reads it to choose samples: its text, then each sample field with
    its distinct values and how many samples carry each. Long values are cut and end in "…"
    (match those with ``contains``)."""
    n = len(series.samples)
    lines = [f"{series.gse}: {series.title}"]
    counts = ""
    if columns is not None:
        covered = set(columns)
        counts = f"; {sum(s.gsm in covered for s in series.samples)} in the NCBI count table"
    lines.append(f"{n} samples{counts}")
    if series.summary:
        lines.append(f"Summary: {series.summary[:1500]}")
    if series.overall_design:
        lines.append(f"Overall design: {series.overall_design[:1200]}")
    if series.relations:
        lines.append(f"Relations: {'; '.join(series.relations[:6])}")
    organisms = Counter(s.organism for s in series.samples if s.organism)
    if any(o != "Homo sapiens" for o in organisms):  # never selected; say so up front
        lines.append(
            "Organisms (only human samples can be selected): "
            + ", ".join(f"{o} x{k}" for o, k in organisms.most_common())
        )

    per_field: dict[str, Counter[str]] = {}
    for s in series.samples:
        for k, v in sample_fields(s).items():
            per_field.setdefault(k, Counter())[v] += 1
    lines.append("Sample fields (each value, then x how many samples have it):")
    for field, values in per_field.items():
        distinct = len(values)
        if field == "title" and distinct > 1:
            shown = list(values)[:_SHOWN_TITLES]
            more = f" (+{distinct - len(shown)} more)" if distinct > len(shown) else ""
            lines.append(f"- title ({distinct} values): " + " | ".join(map(_quote, shown)) + more)
            continue
        if distinct == 1:
            (value, k) = next(iter(values.items()))
            every = "all samples" if k == n else f"x{k}"
            lines.append(f"- {field}: {_quote(value)} ({every})")
            continue
        top = values.most_common(_SHOWN_VALUES)
        numbers = [x for x in (_number(v) for v in values) if x is not None]
        span = (
            f", numbers {min(numbers):g} to {max(numbers):g}"
            if len(numbers) == distinct and distinct > 5
            else ""
        )
        more = f" (+{distinct - len(top)} more)" if distinct > len(top) else ""
        shown = " | ".join(f"{_quote(v)} x{k}" for v, k in top)
        lines.append(f"- {field} ({distinct} values{span}): {shown}{more}")
    return "\n".join(lines)


# ------------------------------------------------------------------------------- rules


class Condition(BaseModel):
    field: str = Field(
        description='a sample field exactly as listed (e.g. "cell type", "title", '
        '"source_name"), or "series" for a fact the summary or design states about every sample'
    )
    equals: list[str] = Field(
        default_factory=list,
        description="holds when the value is exactly one of these; copy values verbatim",
    )
    contains: list[str] = Field(
        default_factory=list,
        description="holds when the value contains one of these, ignoring case (for titles, "
        'long values shown cut with "…", or "series" quotes)',
    )
    min: float | None = Field(
        default=None, description="holds when the value's first number is at least this"
    )
    max: float | None = Field(
        default=None, description="holds when the value's first number is at most this"
    )


class Rule(BaseModel):
    all_of: list[Condition] = Field(description="the sample must meet every condition")


def _holds(c: Condition, fields: dict[str, str], series_text: str) -> bool:
    if c.field == SERIES_FIELD:
        return any(q.casefold() in series_text for q in [*c.equals, *c.contains] if q.strip())
    value = fields.get(c.field)
    if value is None:
        return False
    if value in c.equals:
        return True
    low = value.casefold()
    if any(x.casefold() in low for x in c.contains if x.strip()):
        return True
    if c.min is not None or c.max is not None:
        n = _number(value)
        return n is not None and (c.min is None or n >= c.min) and (c.max is None or n <= c.max)
    return False


def _matches(rules: Sequence[Rule], fields: dict[str, str], series_text: str) -> bool:
    return any(r.all_of and all(_holds(c, fields, series_text) for c in r.all_of) for r in rules)


def describe(rules: Sequence[Rule]) -> str:
    """Rules in words, quoting the record: for hints, logs and reviewers."""

    def cond(c: Condition) -> str:
        parts = []
        if c.equals:
            parts.append(" or ".join(_quote(v) for v in c.equals))
        if c.contains:
            parts.append("contains " + " or ".join(_quote(v) for v in c.contains))
        if c.min is not None or c.max is not None:
            lo = "" if c.min is None else f"{c.min:g}"
            hi = "" if c.max is None else f"{c.max:g}"
            parts.append(f"number in [{lo}, {hi}]")
        return f"{c.field} = " + " / ".join(parts) if parts else f"{c.field} (no test)"

    return " OR ".join(" and ".join(cond(c) for c in r.all_of) for r in rules if r.all_of)


def _problems(
    rules: Sequence[Rule], values: dict[str, set[str]], series_text: str, label: str
) -> list[str]:
    """References to fields or values the record does not have: they never match, and the
    reviewer should see that they were written."""
    out = []
    for r in rules:
        for c in r.all_of:
            if c.field == SERIES_FIELD:
                missing = [q for q in [*c.equals, *c.contains] if q.casefold() not in series_text]
                if missing:
                    out.append(f"{label}: series text does not contain {missing[:3]}")
                continue
            if c.field not in values:
                out.append(f"{label}: no sample field {c.field!r}")
                continue
            absent = [v for v in c.equals if v not in values[c.field]]
            if absent:
                out.append(f"{label}: {c.field} has no value {absent[:3]}")
    return out


# --------------------------------------------------------------------------- selection


class SampleSelection(BaseModel):
    """What code made of the agent's rules for one series. ``case_gsms`` and
    ``control_gsms`` hold every sample the rules put in each arm; ``no_counts_gsms`` are
    the selected samples the NCBI count table lacks (they cannot be analysed)."""

    gse: str
    case_gsms: list[str] = Field(default_factory=list)
    control_gsms: list[str] = Field(default_factory=list)
    unclear_gsms: list[str] = Field(
        default_factory=list,
        description="samples that may belong but the record does not settle it, plus any the "
        "rules put in both arms",
    )
    excluded_gsms: list[str] = Field(default_factory=list, description="every other sample")
    no_counts_gsms: list[str] = Field(default_factory=list)
    counts_checked: bool = False
    case_rule: str = ""
    control_rule: str = ""
    problems: list[str] = Field(default_factory=list)

    def analysable(self, arm: str) -> list[str]:
        gsms = self.case_gsms if arm == "case" else self.control_gsms
        missing = set(self.no_counts_gsms)
        return [g for g in gsms if g not in missing]


def select_samples(
    series: GeoSeries,
    case: Sequence[Rule],
    control: Sequence[Rule],
    unclear: Sequence[Rule] = (),
    *,
    columns: Sequence[str] | None = None,
) -> SampleSelection:
    """Apply the agent's rules to every sample of the series. Non-human samples are never
    selected. ``columns`` (the count table's GSMs) marks selected samples without counts."""
    series_text = f"{series.title} {series.summary} {series.overall_design}".casefold()
    values: dict[str, set[str]] = {}
    for s in series.samples:
        for k, v in sample_fields(s).items():
            values.setdefault(k, set()).add(v)
    out = SampleSelection(
        gse=series.gse,
        case_rule=describe(case),
        control_rule=describe(control),
        problems=[
            *_problems(case, values, series_text, "case"),
            *_problems(control, values, series_text, "control"),
            *_problems(unclear, values, series_text, "unclear"),
        ],
    )
    both = []
    for s in series.samples:
        if s.organism and s.organism != "Homo sapiens":
            out.excluded_gsms.append(s.gsm)
            continue
        fields = sample_fields(s)
        in_case = _matches(case, fields, series_text)
        in_control = _matches(control, fields, series_text)
        if in_case and in_control:
            both.append(s.gsm)
            out.unclear_gsms.append(s.gsm)
        elif in_case:
            out.case_gsms.append(s.gsm)
        elif in_control:
            out.control_gsms.append(s.gsm)
        elif _matches(unclear, fields, series_text):
            out.unclear_gsms.append(s.gsm)
        else:
            out.excluded_gsms.append(s.gsm)
    if both:
        out.problems.append(f"{len(both)} samples matched both arms and were set aside: {both[:5]}")
    if columns is not None:
        covered = set(columns)
        out.counts_checked = True
        out.no_counts_gsms = [g for g in [*out.case_gsms, *out.control_gsms] if g not in covered]
    return out

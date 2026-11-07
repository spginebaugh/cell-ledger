"""The specialist's two Claude-driven steps, each streamed to the browser as Server-Sent Events.

1. **Discover** (``POST /sessions/{id}/discover``): from the user's question, Claude searches
   GEO (keyword search, and the web through Exa when configured), verifies every accession
   against GEO, and returns candidate series with reasons, or clarifying questions when the
   question is ambiguous. Claude never invents an accession: every GSE it reports came back
   from a GEO search or a GEO verification in this very run.

2. **Design** (run by ``cell_ledger_api.pipeline`` as soon as a dataset is ready): for one
   collected series, Claude labels each sample from its GEO record and chooses the one
   two-group contrast that answers the question. The labels are compiled into a
   :class:`SampleSheet`, whose validator refuses any label that is not backed by a verbatim
   quote from the GEO record, and the contrast is checked with ``Contrast.problems``.
   Validation errors go back to Claude once. Nobody confirms the result: a contrast without
   problems runs, one with problems sets the dataset aside, and every choice Claude made is
   recorded in ``decisions`` for the result page.

Events are JSON objects, one per SSE ``data:`` line::

    {"type": "thinking", "delta": "..."}   readable summary of the model's reasoning
    {"type": "tool", "name": "...", "input": {...}, "summary": "..."}
    {"type": "result", "data": {...}}      DiscoveryResult or DesignProposal
    {"type": "error", "message": "..."}
    {"type": "done"}

The model call is behind :class:`TurnRunner` so tests can script Claude's turns.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator, Awaitable, Callable
from typing import Any, Literal, Protocol

import anthropic
from anthropic.lib._parse._transform import to_json_output_format, transform_schema
from anthropic.types.beta import BetaMessage, BetaMessageParam
from pydantic import BaseModel, Field, ValidationError

from cell_ledger.geo import DatasetRecord, GeoClient
from cell_ledger.samplesheet import Assay, Contrast, ContrastStatus, Group, Sample, SampleSheet
from cell_ledger_api.designs import DesignProposal, RunRequest
from cell_ledger_api.discovery import (
    FIND_SERIES_TOOL,
    ExaSearcher,
    find_series_on_web,
)

log = logging.getLogger(__name__)

Event = dict[str, Any]
Emit = Callable[[Event], Awaitable[None]]

MAX_TURNS = 8
MAX_TOKENS = 16000
# A design labels every sample with quoted evidence, so its JSON grows with the series;
# thinking shares this budget. Streaming keeps a long response within request timeouts.
DESIGN_MAX_TOKENS = 64000


# ----------------------------------------------------------------------------- models


class DiscoverRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)


class Candidate(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    title: str
    n_samples: int
    why: str = Field(description="why this series can answer the question")
    case_hint: str = Field(description="which samples would be the case arm")
    control_hint: str = Field(description="which samples would be the control arm")
    concerns: list[str] = Field(default_factory=list)


class Rejected(BaseModel):
    gse: str
    why: str


class DiscoveryResult(BaseModel):
    interpretation: str = Field(description="the question restated as a two-group comparison")
    genes: list[str] = Field(default_factory=list, description="gene symbols the question names")
    clarifying_questions: list[str] = Field(
        default_factory=list,
        description="what must be decided before choosing datasets; empty when clear",
    )
    candidates: list[Candidate] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    queries_tried: list[str] = Field(default_factory=list)


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
    blocking: str | None = Field(
        default=None, description="sample field pairing case and control (e.g. donor), if any"
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


class AgentUnavailable(RuntimeError):
    pass


class DatasetNotReady(LookupError):
    pass


# ------------------------------------------------------------------------- the model


class TurnRunner(Protocol):
    """One request to Claude: stream it, forward thinking to ``emit``, return the message."""

    async def __call__(self, params: dict[str, Any], emit: Emit) -> BetaMessage: ...


def sdk_turn_runner(client: anthropic.AsyncAnthropic) -> TurnRunner:
    async def run(params: dict[str, Any], emit: Emit) -> BetaMessage:
        async with client.beta.messages.stream(**params) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "thinking_delta"
                    and event.delta.thinking
                ):
                    await emit({"type": "thinking", "delta": event.delta.thinking})
            return await stream.get_final_message()

    return run


SYSTEM_DISCOVER = """\
You are cell-ledger, a specialist that finds public bulk RNA-seq datasets in NCBI GEO for a
biologist's question and prepares them for a reproducible two-group differential expression
analysis. You are careful and literal: you report only what GEO confirmed in this session.

Your job in this step:
1. Restate the question as a two-group comparison (case vs control) in one sentence.
2. Search GEO with several differently worded keyword queries (disease synonyms, tissue,
   cell type, treatment). Use the web search tool too when it is available. Run searches in
   parallel when they are independent.
3. Pick the series that can actually answer the question: human bulk RNA-seq with raw counts
   (the search already filters for this), both arms present in the same series, at least
   three samples per arm, clear sample labels. Explain each pick in one or two sentences and
   name which samples would be case and control.
4. Reject series you looked at but would not use, and say why in a few words.
5. If the question is ambiguous in a way that changes which datasets qualify (which tissue,
   which control, treated or untreated, which time point), ask clarifying questions instead
   of guessing, and still list the candidates that fit every reading.

Never report an accession that did not come back from a search or verification in this
conversation. Never invent sample counts or titles; copy them from the tool results.
Prefer fewer, better candidates (at most eight). Keep prose short.
"""

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
matrix), a blocking field when case and control come from the same donors, a short rationale,
and a confidence. Prefer the cleanest reading: the untreated or healthy control over other
arms, one time point over pooled ones when pooling would mix effects, and the largest arms
that stay homogeneous. Each arm needs at least three samples; if the series cannot give
that, still return the best contrast and say so in decisions (it will be set aside).

Do not ask questions; there is no one to answer them. Where the record leaves a real choice
(which control to use, whether to pool time points, whether treated samples count), make it
and record it as one line in decisions, naming the alternative you rejected.
"""


class Agent:
    def __init__(
        self,
        geo: GeoClient,
        *,
        turn: TurnRunner | None = None,
        exa: ExaSearcher | None = None,
        model: str = "claude-opus-5-5",
        effort: str = "medium",
    ) -> None:
        self._geo = geo
        self._turn = turn
        self._exa = exa
        self._model = model
        self._effort = effort

    @property
    def available(self) -> bool:
        return self._turn is not None

    def _params(self, **kw: Any) -> dict[str, Any]:
        return {
            "model": self._model,
            "max_tokens": MAX_TOKENS,
            "thinking": {"type": "adaptive", "display": "summarized"},
            "output_config": {"effort": self._effort},
            # Safety classifiers can misfire on biomedical text; a decline re-runs the
            # request on Anthropic's recommended substitute instead of failing the user.
            "betas": ["server-side-fallback-2026-07-01"],
            "fallbacks": "default",
            **kw,
        }

    # ------------------------------------------------------------- discover

    def _discover_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = [
            {
                "name": "search_geo",
                "description": (
                    "Keyword search of NCBI GEO for human bulk RNA-seq series with NCBI raw "
                    "counts. Pass several differently worded queries at once; results are "
                    "merged and say which queries found each series."
                ),
                "strict": True,
                "eager_input_streaming": True,
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "queries": {"type": "array", "items": {"type": "string"}},
                        "since": {
                            "type": ["integer", "null"],
                            "description": "only series published in or after this year",
                        },
                    },
                    "required": ["queries", "since"],
                    "additionalProperties": False,
                },
            },
            {
                "name": "verify_geo_series",
                "description": (
                    "Check accessions you got from anywhere else (a paper, memory, the web) "
                    "against GEO. Only accessions that exist and are human bulk RNA-seq with "
                    "raw counts come back as hits."
                ),
                "strict": True,
                "input_schema": {
                    "type": "object",
                    "properties": {"gses": {"type": "array", "items": {"type": "string"}}},
                    "required": ["gses"],
                    "additionalProperties": False,
                },
            },
        ]
        if self._exa is not None:
            tools.append({**FIND_SERIES_TOOL, "strict": True})
        return tools

    async def _run_tool(self, name: str, args: dict[str, Any]) -> tuple[str, str, list[str]]:
        """Execute one tool.

        Returns the result text for Claude, a one-line summary for the UI, and the
        accessions GEO confirmed eligible (the only ones the final answer may name)."""
        if name == "search_geo":
            queries = [q for q in args.get("queries", []) if isinstance(q, str) and q.strip()]
            if not queries:
                return "error: no queries given", "search_geo: no queries", []
            since = args.get("since")
            res = await self._geo.search_series(
                queries[:10], limit_per_query=25, since=since if isinstance(since, int) else None
            )
            hits = [
                {
                    "gse": h.gse,
                    "title": h.title,
                    "n_samples": h.n_samples,
                    "published": h.published.isoformat() if h.published else None,
                    "summary": h.summary[:400],
                    "matched_queries": h.matched_queries,
                }
                for h in res.hits[:40]
            ]
            stats = [
                {"query": q.query, "total": q.total, "returned": q.returned} for q in res.queries
            ]
            return (
                json.dumps({"queries": stats, "hits": hits}, ensure_ascii=False),
                f"searched GEO: {len(queries)} queries, {len(res.hits)} series",
                [h.gse for h in res.hits],
            )
        if name == "verify_geo_series":
            gses = [g for g in args.get("gses", []) if isinstance(g, str)]
            try:
                res = await self._geo.verify_series(gses)
            except ValueError as e:
                return f"error: {e}", "verify: invalid accession", []
            hits = [
                {
                    "gse": h.gse,
                    "title": h.title,
                    "n_samples": h.n_samples,
                    "summary": h.summary[:400],
                }
                for h in res.hits
            ]
            return (
                json.dumps({"hits": hits, "ineligible": res.ineligible}, ensure_ascii=False),
                f"verified {len(gses)}: {len(hits)} eligible",
                [h.gse for h in res.hits],
            )
        if name == FIND_SERIES_TOOL["name"] and self._exa is not None:
            res = await find_series_on_web(
                self._exa, self._geo, str(args.get("query", "")), str(args.get("objective", ""))
            )
            payload = {
                "verified": [
                    {
                        "gse": v.hit.gse,
                        "title": v.hit.title,
                        "n_samples": v.hit.n_samples,
                        "summary": v.hit.summary[:400],
                        "found_at": v.found_at[:3],
                    }
                    for v in res.verified
                ],
                "rejected": res.rejected,
            }
            return (
                json.dumps(payload, ensure_ascii=False),
                f"web search: {len(res.verified)} verified, {len(res.rejected)} rejected",
                [v.hit.gse for v in res.verified],
            )
        return f"error: unknown tool {name}", f"unknown tool {name}", []

    async def discover(self, question: str, emit: Emit) -> DiscoveryResult:
        if self._turn is None:
            raise AgentUnavailable("Claude is not configured (CELL_LEDGER_ANTHROPIC_API_KEY)")
        messages: list[BetaMessageParam] = [{"role": "user", "content": question}]
        params = self._params(
            system=SYSTEM_DISCOVER,
            tools=self._discover_tools(),
            output_config={
                "effort": self._effort,
                "format": to_json_output_format(DiscoveryResult),
            },
        )
        seen: set[str] = set()  # accessions GEO itself returned during this run
        for _ in range(MAX_TURNS):
            message = await self._turn({**params, "messages": messages}, emit)
            if message.stop_reason == "refusal":
                raise AgentUnavailable("the model declined this request")
            tool_uses = [b for b in message.content if b.type == "tool_use"]
            if message.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": message.content})
                continue
            if not tool_uses or message.stop_reason == "max_tokens":
                break
            messages.append({"role": "assistant", "content": message.content})
            results: list[dict[str, Any]] = []
            for use in tool_uses:
                args = use.input if isinstance(use.input, dict) else {}
                try:
                    text, summary, confirmed = await self._run_tool(use.name, args)
                    is_error = text.startswith("error:")
                except Exception as e:  # a failed search is a tool error, not a dead agent
                    log.warning("tool %s failed: %s", use.name, e)
                    text = f"error: {type(e).__name__}: {e}"
                    summary, is_error, confirmed = f"{use.name} failed", True, []
                seen.update(confirmed)
                await emit({"type": "tool", "name": use.name, "input": args, "summary": summary})
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": text,
                        "is_error": is_error,
                    }
                )
            messages.append({"role": "user", "content": results})  # type: ignore[arg-type]
        else:
            raise AgentUnavailable(f"gave up after {MAX_TURNS} tool turns")
        text = "".join(b.text for b in message.content if b.type == "text")
        try:
            result = DiscoveryResult.model_validate_json(text)
        except ValidationError as e:
            raise AgentUnavailable(f"the model returned an unreadable result: {e}") from e
        # Belt and braces: drop any accession GEO did not hand us in this run.
        kept = [c for c in result.candidates if c.gse in seen]
        invented = [c.gse for c in result.candidates if c.gse not in seen]
        if invented:
            log.warning("discover: dropped unverified accessions %s", invented)
            result.rejected.extend(
                Rejected(gse=g, why="not confirmed by GEO in this run") for g in invented
            )
        result.candidates = kept
        return result

    # --------------------------------------------------------------- design

    @staticmethod
    def _record_text(record: DatasetRecord) -> str:
        rows = []
        for s in record.samples:
            if not s.in_counts or s.exclusions:
                continue
            rows.append(
                {
                    "gsm": s.gsm,
                    "title": s.title,
                    "source_name": s.source_name,
                    "characteristics": s.characteristics,
                }
            )
        doc = {
            "gse": record.gse,
            "title": record.title,
            "summary": record.summary[:3000],
            "overall_design": record.overall_design[:2000],
            "n_samples_with_counts": len(rows),
            "samples": rows,
        }
        return json.dumps(doc, ensure_ascii=False, indent=1)

    @staticmethod
    def compile(
        record: DatasetRecord, out: DesignOutput, genes: list[str]
    ) -> tuple[DesignProposal | None, list[str]]:
        """Turn Claude's labels into a validated design; returns (proposal, errors)."""
        by_gsm = {s.gsm: s for s in record.samples}
        errors: list[str] = []
        samples: list[Sample] = []
        for lab in out.samples:
            rec = by_gsm.get(lab.gsm)
            if rec is None:
                errors.append(f"{lab.gsm}: not a sample of {record.gse}")
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
                        donor=lab.donor,
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
        try:
            # Confirmed, not proposed: the pipeline runs what passes ``problems`` with no one
            # in between, and the result page shows the decisions instead of a confirm button.
            contrast = Contrast(
                gse=record.gse,
                name=_slug(c.name),
                case_label=c.case_label,
                control_label=c.control_label,
                case_gsms=c.case_gsms,
                control_gsms=c.control_gsms,
                blocking=c.blocking,
                confidence=c.confidence,
                status=ContrastStatus.CONFIRMED,
                rationale=c.rationale,
            )
        except ValidationError as e:
            errors.extend(f"contrast {c.name}: {err['msg']}" for err in e.errors())
            return None, errors
        design = RunRequest(
            samplesheet=sheet, contrasts=[contrast], genes=list(dict.fromkeys(genes))
        )
        return (
            DesignProposal(
                design=design,
                problems=contrast.problems(sheet),
                qualifications=contrast.qualifications(sheet),
                decisions=out.decisions,
                notes=out.notes,
            ),
            errors,
        )

    async def design(self, record: DatasetRecord, req: DesignRequest, emit: Emit) -> DesignProposal:
        if self._turn is None:
            raise AgentUnavailable("Claude is not configured (CELL_LEDGER_ANTHROPIC_API_KEY)")
        if record.status != "ready":
            raise DatasetNotReady(f"{record.gse} is {record.status}")
        prompt = f"Question: {req.question}\n"
        if req.context:
            prompt += f"Context from the dataset search:\n{req.context}\n"
        if req.genes:
            prompt += f"Genes of interest: {', '.join(req.genes)}\n"
        prompt += "\nGEO record (only samples that have counts):\n" + self._record_text(record)
        messages: list[BetaMessageParam] = [{"role": "user", "content": prompt}]
        params = self._params(
            system=SYSTEM_DESIGN,
            max_tokens=DESIGN_MAX_TOKENS,
            output_config={"effort": self._effort, "format": to_json_output_format(DesignOutput)},
        )
        proposal: DesignProposal | None = None
        errors: list[str] = []
        for attempt in (1, 2):
            message = await self._turn({**params, "messages": messages}, emit)
            if message.stop_reason == "refusal":
                raise AgentUnavailable("the model declined this request")
            if message.stop_reason == "max_tokens":
                errors = [
                    f"the design was cut off at {DESIGN_MAX_TOKENS} tokens "
                    f"({len(record.samples)} samples)"
                ]
                break
            text = "".join(b.text for b in message.content if b.type == "text")
            try:
                out = DesignOutput.model_validate_json(text)
            except ValidationError as e:
                errors = [f"unreadable output: {e}"]
                break
            proposal, errors = self.compile(record, out, req.genes)
            if proposal is not None:
                proposal.attempts = attempt
                proposal.validation_errors = errors
            if not errors or attempt == 2:
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
            messages.append(
                {
                    "role": "user",
                    "content": "The validator rejected these labels. Fix them by quoting the "
                    "record verbatim (or set group to unknown with empty evidence) and return "
                    "the whole design again:\n- " + "\n- ".join(errors[:40]),
                }
            )
        if proposal is None:
            raise AgentUnavailable("could not build a valid design: " + "; ".join(errors[:5]))
        return proposal


def _slug(name: str) -> str:
    import re

    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return s or "contrast"


# -------------------------------------------------------------------------- SSE


async def sse(gen: AsyncIterator[Event]) -> AsyncIterator[bytes]:
    async for event in gen:
        yield f"data: {json.dumps(event, default=str)}\n\n".encode()


def _schema_check() -> None:
    """Fail at import time if the schemas cannot be made strict (keeps tests honest)."""
    transform_schema(DiscoveryResult)
    transform_schema(DesignOutput)


_schema_check()

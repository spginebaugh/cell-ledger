"""The discover step: from the user's question, Claude searches GEO with the tools in
:mod:`.tools` and returns candidate series with reasons, or clarifying questions when the
question is ambiguous.

The code around the model keeps a :class:`DiscoveryTrace` of every query, every accession GEO
confirmed and what it cost, and drops any candidate GEO never confirmed in this run.
"""

from __future__ import annotations

import hashlib
import json
import logging
import time
from collections.abc import Sequence
from typing import Annotated, Any

from anthropic.lib._parse._transform import transform_schema
from anthropic.types.beta import BetaMessageParam, BetaToolResultBlockParam
from pydantic import BaseModel, Field, StringConstraints, ValidationError

from cell_ledger.geo import GeoClient
from cell_ledger_api.agent.llm import (
    DEFAULT_EFFORT,
    DEFAULT_MODEL,
    MAX_TURNS,
    NOT_CONFIGURED,
    AgentUnavailable,
    Emit,
    TurnRunner,
    final_text,
    reject_refusal,
    request_params,
)
from cell_ledger_api.agent.tools import ToolCall, execute, geo_tools
from cell_ledger_api.discovery import ExaSearcher

log = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- models


class DiscoverRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    answers: list[Annotated[str, StringConstraints(max_length=2000)]] = Field(
        default_factory=list,
        max_length=10,
        description="the user's answers to the clarifying questions an earlier discovery of "
        "this question asked, in order; each at most 2000 characters",
    )


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


class ClarifyingQuestion(BaseModel):
    question: str = Field(description="one decision the user must make before datasets qualify")
    options: list[str] = Field(
        default_factory=list,
        description="suggested answers when the choice is enumerable (the tissues, control "
        "types or time points the results actually offer); empty for an open question",
    )
    why: str = Field(description="what changes with the answer: which series would qualify")


class DiscoveryOutput(BaseModel):
    """What Claude returns from the discover step (the JSON schema it is held to)."""

    interpretation: str = Field(description="the question restated as a two-group comparison")
    genes: list[str] = Field(default_factory=list, description="gene symbols the question names")
    out_of_scope: str | None = Field(
        default=None,
        description="set, with the reason, when no human bulk RNA-seq series with raw counts "
        "in GEO can answer the question (another organism, single-cell, microarray, "
        "proteomics, not a gene expression question); candidates must then be empty",
    )
    clarifying_questions: list[ClarifyingQuestion] = Field(
        default_factory=list,
        description="what must be decided before choosing datasets; empty when clear",
    )
    candidates: list[Candidate] = Field(default_factory=list)
    rejected: list[Rejected] = Field(default_factory=list)
    queries_tried: list[str] = Field(default_factory=list)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0
    cache_creation_input_tokens: int = 0

    def add(self, usage: Any) -> None:
        for field in type(self).model_fields:
            value = getattr(usage, field, None)
            if isinstance(value, int):
                setattr(self, field, getattr(self, field) + value)


class DiscoveryTrace(BaseModel):
    """Recorded by the code around the model, never self-reported: which queries ran, which
    accessions each returned, which Claude saw, and what it cost. The evals read this to tell
    a search miss (never returned) from a judgment miss (returned, then rejected or ignored)."""

    turns: int = 0
    calls: list[ToolCall] = Field(default_factory=list)
    seen: list[str] = Field(
        default_factory=list, description="every accession GEO confirmed in this run"
    )
    invented: list[str] = Field(
        default_factory=list,
        description="accessions the model named that GEO never confirmed; dropped",
    )
    usage: Usage = Field(default_factory=Usage)
    elapsed_seconds: float = 0.0


class DiscoveryResult(DiscoveryOutput):
    """Claude's output plus the trace the code recorded around it."""

    trace: DiscoveryTrace = Field(default_factory=DiscoveryTrace)


transform_schema(DiscoveryOutput)  # fail at import if the schema cannot be made strict


# ----------------------------------------------------------------------------- prompt


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
   of guessing, and still list the candidates that fit every reading. Give each question the
   options the results actually offer (the tissues, controls or time points you saw) when the
   choice is enumerable, and say what changes with the answer. When the user has already
   answered (a "Clarifications from the user" block follows the question), treat those
   answers as settled and do not ask about them again.
6. If no human bulk RNA-seq series with raw counts in GEO can answer the question at all
   (another organism, single-cell, microarray, proteomics, not a gene expression question),
   say so in out_of_scope with the reason and return no candidates. A question that is in
   scope but finds nothing is not out of scope: return no candidates and say what you tried.

Never report an accession that did not come back from a search or verification in this
conversation. Never invent sample counts or titles; copy them from the tool results.
Prefer fewer, better candidates (at most eight). Keep prose short.
"""


def discovery_prompt(question: str, answers: Sequence[str] = ()) -> str:
    """The user turn for the discover step. One function so the API and the evals agree."""
    kept = [a.strip() for a in answers if a and a.strip()]
    if not kept:
        return question
    lines = "\n".join(f"- {a}" for a in kept)
    return (
        f"{question}\n\nClarifications from the user (answers to the questions you asked "
        f"earlier; treat them as settled and do not ask about them again):\n{lines}"
    )


# ------------------------------------------------------------------------------- step


class Discoverer:
    def __init__(
        self,
        geo: GeoClient,
        *,
        turn: TurnRunner | None = None,
        exa: ExaSearcher | None = None,
        model: str = DEFAULT_MODEL,
        effort: str = DEFAULT_EFFORT,
    ) -> None:
        self._turn = turn
        self._tools = geo_tools(geo, exa)
        self._model = model
        self._effort = effort

    @property
    def available(self) -> bool:
        return self._turn is not None

    def tool_definitions(self) -> list[dict[str, Any]]:
        return [t.definition for t in self._tools.values()]

    def fingerprint(self) -> str:
        """Hash of everything that shapes a discover request except the question: the system
        prompt, the tool definitions, the model and the effort. The evals stamp every run with
        it, so a prompt or tool change between two runs is visible in the results."""
        payload = {
            "system": SYSTEM_DISCOVER,
            "tools": self.tool_definitions(),
            "model": self._model,
            "effort": self._effort,
        }
        return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()

    async def discover(
        self, question: str, emit: Emit, *, answers: Sequence[str] = ()
    ) -> DiscoveryResult:
        if self._turn is None:
            raise AgentUnavailable(NOT_CONFIGURED)
        started = time.monotonic()
        trace = DiscoveryTrace()
        messages: list[BetaMessageParam] = [
            {"role": "user", "content": discovery_prompt(question, answers)}
        ]
        params = request_params(
            model=self._model,
            effort=self._effort,
            system=SYSTEM_DISCOVER,
            output=DiscoveryOutput,
            tools=self.tool_definitions(),
        )
        seen: dict[str, None] = {}  # accessions GEO itself returned during this run, in order
        for _ in range(MAX_TURNS):
            message = await self._turn({**params, "messages": messages}, emit)
            trace.turns += 1
            trace.usage.add(message.usage)
            reject_refusal(message)
            if message.stop_reason == "pause_turn":
                messages.append({"role": "assistant", "content": message.content})
                continue
            tool_uses = [b for b in message.content if b.type == "tool_use"]
            if not tool_uses or message.stop_reason == "max_tokens":
                break
            messages.append({"role": "assistant", "content": message.content})
            results: list[BetaToolResultBlockParam] = []
            for use in tool_uses:
                args = use.input if isinstance(use.input, dict) else {}
                call, result = await execute(self._tools, use.name, args)
                trace.calls.append(call)
                seen.update(dict.fromkeys(call.confirmed))
                await emit(
                    {"type": "tool", "name": use.name, "input": args, "summary": result.summary}
                )
                results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": use.id,
                        "content": result.content,
                        "is_error": result.is_error,
                    }
                )
            messages.append({"role": "user", "content": results})
        else:
            raise AgentUnavailable(f"gave up after {MAX_TURNS} tool turns")
        try:
            output = DiscoveryOutput.model_validate_json(final_text(message))
        except ValidationError as e:
            raise AgentUnavailable(f"the model returned an unreadable result: {e}") from e
        invented = _keep_confirmed(output, seen)
        trace.seen = list(seen)
        trace.invented = invented
        trace.elapsed_seconds = round(time.monotonic() - started, 3)
        return DiscoveryResult(**output.model_dump(), trace=trace)


def _keep_confirmed(output: DiscoveryOutput, seen: dict[str, None]) -> list[str]:
    """Belt and braces: move every candidate GEO did not hand us in this run to ``rejected``,
    and return those accessions."""
    invented = [c.gse for c in output.candidates if c.gse not in seen]
    if invented:
        log.warning("discover: dropped unverified accessions %s", invented)
        output.rejected.extend(
            Rejected(gse=g, why="not confirmed by GEO in this run") for g in invented
        )
    output.candidates = [c for c in output.candidates if c.gse in seen]
    if output.out_of_scope and output.candidates:
        # An out-of-scope verdict with candidates attached is a contradiction; the candidates
        # GEO confirmed win.
        log.warning("discover: out_of_scope set alongside %d candidates", len(output.candidates))
        output.out_of_scope = None
    return invented

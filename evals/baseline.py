"""The general-purpose baseline: the same Claude model with web search and web fetch, and
nothing else.

It gets the same question, the same requirements in plain words (eligibility, both arms in
one series, at most 10 datasets, the exact samples per arm) and the same output schema as the
specialist, except that it names its samples' GSM accessions directly where the specialist
writes rules over GEO fields. It has no GEO tools, so every accession it names is checked
afterwards against GEO by code; the ones GEO has never heard of are its fabrication rate.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from anthropic.lib._parse._transform import to_json_output_format
from anthropic.types.beta import BetaMessageParam
from pydantic import Field, ValidationError

from cell_ledger.geo import GeoClient
from cell_ledger_api.agent.discover import CandidateBase, DiscoveryFields, discovery_prompt
from cell_ledger_api.agent.llm import MAX_TOKENS, MAX_TURNS, TurnRunner, final_text, quiet
from evals.cases import Case
from evals.records import Conditions, RunRecord, Turn, derive_action
from evals.specialist import verify_candidates

BASELINE_SYSTEM = """\
A biologist is looking for public datasets in NCBI GEO to answer a question with a two-group
differential expression comparison. They need human bulk RNA-seq series (GSE accessions) that
have NCBI-generated raw counts available, with both arms of the comparison in the same series
and at least three samples per arm. Their analysis takes at most 10 series.

Restate the question as a two-group comparison, find series that can answer it, and for each
explain why and list the GSM accessions of the samples in each arm (case_gsms, control_gsms),
copied from the GEO records. Choose samples that fit the question exactly: a series can
qualify through a subset of its samples, and cell lines, organoids, primary tissue and
xenografts, parental and engineered lines, and pediatric and adult donors are not
interchangeable. List series you considered but would not use, with the reason. If the
question is broad or ambiguous in a way that changes which datasets or samples qualify, or
more than 10 series would qualify, ask clarifying questions (with options where the choice is
enumerable). If no such dataset can exist for this question (another organism, single-cell,
microarray, not a gene expression question), say so in out_of_scope. Report accessions
exactly as written in your sources.
"""

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260318",
    "name": "web_search",
    "max_uses": 15,
}
WEB_FETCH_TOOL: dict[str, Any] = {
    "type": "web_fetch_20260209",
    "name": "web_fetch",
    "max_uses": 20,
}
WEB_TOOLS = [WEB_SEARCH_TOOL, WEB_FETCH_TOOL]


class BaselineCandidate(CandidateBase):
    case_gsms: list[str] = Field(
        default_factory=list, description="GSM accessions of the case arm's samples"
    )
    control_gsms: list[str] = Field(
        default_factory=list, description="GSM accessions of the control arm's samples"
    )


class BaselineOutput(DiscoveryFields):
    """The specialist's output schema with sample accessions in place of sample rules."""

    candidates: list[BaselineCandidate] = Field(default_factory=list)


def baseline_fingerprint(model: str, effort: str, web_search: bool) -> str:
    payload = {
        "system": BASELINE_SYSTEM,
        "tools": WEB_TOOLS if web_search else [],
        "schema": BaselineOutput.model_json_schema(),
        "model": model,
        "effort": effort,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def baseline_turn(
    turn: TurnRunner, prompt: str, *, model: str, effort: str, web_search: bool
) -> tuple[BaselineOutput, dict[str, int]]:
    """One question to plain Claude; server-side web search and fetch need no tool loop on our
    side, only re-sending on ``pause_turn``."""
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort, "format": to_json_output_format(BaselineOutput)},
        "system": BASELINE_SYSTEM,
        "cache_control": {"type": "ephemeral"},  # as the specialist: paused turns re-read cheaply
    }
    if web_search:
        params["tools"] = WEB_TOOLS
    messages: list[BetaMessageParam] = [{"role": "user", "content": prompt}]
    usage = {
        "input_tokens": 0,
        "output_tokens": 0,
        "web_search_requests": 0,
        "web_fetch_requests": 0,
    }
    for _ in range(MAX_TURNS):
        message = await turn({**params, "messages": messages}, quiet)
        u = message.usage
        usage["input_tokens"] += (
            u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        )
        usage["output_tokens"] += u.output_tokens
        if u.server_tool_use is not None:
            usage["web_search_requests"] += u.server_tool_use.web_search_requests or 0
            usage["web_fetch_requests"] += getattr(u.server_tool_use, "web_fetch_requests", 0) or 0
        if message.stop_reason == "refusal":
            raise RuntimeError("the model declined this request")
        if message.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": message.content})
            continue
        break
    else:
        raise RuntimeError(f"gave up after {MAX_TURNS} paused turns")
    try:
        return BaselineOutput.model_validate_json(final_text(message)), usage
    except ValidationError as e:
        raise RuntimeError(f"unreadable result: {e}") from e


async def run_baseline(
    case: Case,
    *,
    geo: GeoClient,
    turn: TurnRunner,
    conditions: Conditions,
    repeat: int = 1,
) -> RunRecord:
    turns: list[Turn] = []
    outputs: list[BaselineOutput] = []
    started = time.monotonic()

    async def one(answers: list[str]) -> BaselineOutput | None:
        t0 = time.monotonic()
        try:
            output, usage = await baseline_turn(
                turn,
                discovery_prompt(case.prompt, answers),
                model=conditions.model,
                effort=conditions.effort,
                web_search=conditions.web_search,
            )
        except Exception as e:
            turns.append(
                Turn(
                    answers=answers,
                    action="error",
                    elapsed_seconds=time.monotonic() - t0,
                    error=f"{type(e).__name__}: {e}",
                )
            )
            return None
        out = output.model_dump(mode="json")
        turns.append(
            Turn(
                answers=answers,
                action=derive_action(out),
                output=out,
                elapsed_seconds=time.monotonic() - t0,
                input_tokens=usage["input_tokens"],
                output_tokens=usage["output_tokens"],
                web_search_requests=usage["web_search_requests"],
                web_fetch_requests=usage["web_fetch_requests"],
            )
        )
        outputs.append(output)
        return output

    first = await one([])
    if first is not None and turns[-1].action == "ask" and case.answers:
        await one(list(case.answers))

    final = outputs[-1] if outputs else None
    candidates = (
        list(dict.fromkeys(c.gse.strip().upper() for c in final.candidates)) if final else []
    )
    return RunRecord(
        case_id=case.id,
        system="baseline",
        repeat=repeat,
        conditions=conditions,
        turns=turns,
        final_action=turns[-1].action,
        candidates=candidates,
        candidate_details={
            c.gse.strip().upper(): {
                "title": c.title,
                "why": c.why,
                "case_hint": c.case_hint,
                "control_hint": c.control_hint,
            }
            for c in (final.candidates if final else [])
        },
        rejected=[r.gse.strip().upper() for r in final.rejected] if final else [],
        selections={
            c.gse.strip().upper(): {
                "case": [g.strip().upper() for g in c.case_gsms],
                "control": [g.strip().upper() for g in c.control_gsms],
            }
            for c in (final.candidates if final else [])
        },
        questions=[q.model_dump() for q in outputs[0].clarifying_questions] if outputs else [],
        out_of_scope=final.out_of_scope if final else None,
        verification=await verify_candidates(geo, candidates),
        elapsed_seconds=round(time.monotonic() - started, 3),
        input_tokens=sum(t.input_tokens for t in turns),
        output_tokens=sum(t.output_tokens for t in turns),
        web_search_requests=sum(t.web_search_requests for t in turns),
        web_fetch_requests=sum(t.web_fetch_requests for t in turns),
        error=turns[-1].error,
    )

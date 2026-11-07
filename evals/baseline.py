"""The general-purpose baseline: the same Claude model with web search and nothing else.

It gets the same question, the same eligibility requirement in plain words, and the same
output schema as the specialist, so the same scorer reads both. It has no GEO tools, so every
accession it names is checked afterwards against GEO by code; the ones GEO has never heard of
are its fabrication rate.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from anthropic.lib._parse._transform import to_json_output_format
from anthropic.types.beta import BetaMessageParam
from pydantic import ValidationError

from cell_ledger.geo import GeoClient
from cell_ledger_api.agent import (
    MAX_TOKENS,
    MAX_TURNS,
    DiscoveryOutput,
    TurnRunner,
    discovery_prompt,
)
from evals.cases import Case
from evals.records import Conditions, RunRecord, Turn, derive_action
from evals.specialist import _quiet, verify_candidates

BASELINE_SYSTEM = """\
A biologist is looking for public datasets in NCBI GEO to answer a question with a two-group
differential expression comparison. They need human bulk RNA-seq series (GSE accessions) that
have NCBI-generated raw counts available, with both arms of the comparison in the same series
and at least three samples per arm.

Restate the question as a two-group comparison, find series that can answer it, and for each
explain why and which samples would be case and control. List series you considered but
would not use, with the reason. If the question is ambiguous in a way that changes which
datasets qualify, ask clarifying questions (with options where the choice is enumerable). If
no such dataset can exist for this question (another organism, single-cell, microarray, not a
gene expression question), say so in out_of_scope. Report accessions exactly as written in
your sources.
"""

WEB_SEARCH_TOOL: dict[str, Any] = {
    "type": "web_search_20260318",
    "name": "web_search",
    "max_uses": 15,
}


def baseline_fingerprint(model: str, effort: str, web_search: bool) -> str:
    payload = {
        "system": BASELINE_SYSTEM,
        "tools": [WEB_SEARCH_TOOL] if web_search else [],
        "model": model,
        "effort": effort,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


async def baseline_turn(
    turn: TurnRunner, prompt: str, *, model: str, effort: str, web_search: bool
) -> tuple[DiscoveryOutput, dict[str, int]]:
    """One question to plain Claude; server-side web search needs no tool loop on our side,
    only re-sending on ``pause_turn``."""
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort, "format": to_json_output_format(DiscoveryOutput)},
        "system": BASELINE_SYSTEM,
    }
    if web_search:
        params["tools"] = [WEB_SEARCH_TOOL]
    messages: list[BetaMessageParam] = [{"role": "user", "content": prompt}]
    usage = {"input_tokens": 0, "output_tokens": 0, "web_search_requests": 0}
    for _ in range(MAX_TURNS):
        message = await turn({**params, "messages": messages}, _quiet)
        u = message.usage
        usage["input_tokens"] += (
            u.input_tokens + (u.cache_read_input_tokens or 0) + (u.cache_creation_input_tokens or 0)
        )
        usage["output_tokens"] += u.output_tokens
        if u.server_tool_use is not None:
            usage["web_search_requests"] += u.server_tool_use.web_search_requests or 0
        if message.stop_reason == "refusal":
            raise RuntimeError("the model declined this request")
        if message.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": message.content})
            continue
        break
    else:
        raise RuntimeError(f"gave up after {MAX_TURNS} paused turns")
    text = "".join(b.text for b in message.content if b.type == "text")
    try:
        return DiscoveryOutput.model_validate_json(text), usage
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
    outputs: list[DiscoveryOutput] = []
    started = time.monotonic()

    async def one(answers: list[str]) -> DiscoveryOutput | None:
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
        questions=[q.model_dump() for q in outputs[0].clarifying_questions] if outputs else [],
        out_of_scope=final.out_of_scope if final else None,
        verification=await verify_candidates(geo, candidates),
        elapsed_seconds=round(time.monotonic() - started, 3),
        input_tokens=sum(t.input_tokens for t in turns),
        output_tokens=sum(t.output_tokens for t in turns),
        web_search_requests=sum(t.web_search_requests for t in turns),
        error=turns[-1].error,
    )

"""Run the specialist's discover step on a case, exactly as the API would, and record it.

The ``Agent`` is built directly (no FastAPI, no database). A first turn asks the question; if
the agent asks clarifying questions and the case scripts answers, a second turn sends them
the same way the UI does. Every accession GEO returned, per query, lands in the record from
the agent's trace, so scoring can separate a search miss from a judgment miss.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from typing import Any

from cell_ledger.geo import GeoClient
from cell_ledger_api.agent import Agent, AgentUnavailable, DiscoveryResult, TurnRunner
from cell_ledger_api.discovery import ExaSearcher
from evals.cases import Case
from evals.records import Conditions, RunRecord, Turn, Verification, derive_action


async def _quiet(_: dict[str, Any]) -> None:
    pass


async def verify_candidates(geo: GeoClient, gses: Sequence[str]) -> Verification:
    """Code's own check of what a system recommended: eligible, merely existing, or absent."""
    valid = [g for g in gses if g.startswith("GSE") and g[3:].isdigit()]
    out = Verification(invalid=[g for g in gses if g not in valid])
    if not valid:
        return out
    eligible = {h.gse for h in (await geo.verify_series(valid)).hits}
    existing = set(await geo.exists_series(valid)) | eligible
    out.eligible = [g for g in valid if g in eligible]
    out.exists_only = [g for g in valid if g in existing and g not in eligible]
    out.missing = [g for g in valid if g not in existing]
    return out


def _turn(
    result: DiscoveryResult | None, answers: list[str], elapsed: float, error: str | None
) -> Turn:
    if result is None:
        return Turn(answers=answers, action="error", elapsed_seconds=elapsed, error=error)
    out = result.model_dump(mode="json")
    return Turn(
        answers=answers,
        action=derive_action(out),
        output=out,
        elapsed_seconds=elapsed,
        input_tokens=result.trace.usage.input_tokens
        + result.trace.usage.cache_read_input_tokens
        + result.trace.usage.cache_creation_input_tokens,
        output_tokens=result.trace.usage.output_tokens,
    )


async def run_specialist(
    case: Case,
    *,
    geo: GeoClient,
    turn: TurnRunner,
    exa: ExaSearcher | None,
    conditions: Conditions,
    repeat: int = 1,
) -> RunRecord:
    agent = Agent(geo, turn=turn, exa=exa, model=conditions.model, effort=conditions.effort)
    turns: list[Turn] = []
    results: list[DiscoveryResult] = []
    started = time.monotonic()

    async def one(answers: list[str]) -> DiscoveryResult | None:
        t0 = time.monotonic()
        try:
            result = await agent.discover(case.prompt, _quiet, answers=answers)
        except AgentUnavailable as e:
            turns.append(_turn(None, answers, time.monotonic() - t0, str(e)))
            return None
        except Exception as e:  # network, SDK: the run is an error, not a crash of the suite
            turns.append(_turn(None, answers, time.monotonic() - t0, f"{type(e).__name__}: {e}"))
            return None
        turns.append(_turn(result, answers, time.monotonic() - t0, None))
        results.append(result)
        return result

    first = await one([])
    if first is not None and turns[-1].action == "ask" and case.answers:
        await one(list(case.answers))

    final = results[-1] if results else None
    seen: dict[str, None] = {}
    per_query: dict[str, list[str]] = {}
    invented: dict[str, None] = {}
    for r in results:
        seen.update(dict.fromkeys(r.trace.seen))
        invented.update(dict.fromkeys(r.trace.invented))
        for call in r.trace.calls:
            for q in call.queries:
                merged = per_query.setdefault(q.query, [])
                merged.extend(g for g in q.gses if g not in merged)
    candidates = [c.gse for c in final.candidates] if final else []
    return RunRecord(
        case_id=case.id,
        system="specialist",
        repeat=repeat,
        conditions=conditions,
        turns=turns,
        final_action=turns[-1].action,
        candidates=candidates,
        candidate_details={
            c.gse: {
                "title": c.title,
                "why": c.why,
                "case_hint": c.case_hint,
                "control_hint": c.control_hint,
            }
            for c in (final.candidates if final else [])
        },
        rejected=[r.gse for r in final.rejected] if final else [],
        questions=[q.model_dump() for q in results[0].clarifying_questions] if results else [],
        out_of_scope=final.out_of_scope if final else None,
        seen=list(seen),
        per_query=per_query,
        invented=list(invented),
        verification=await verify_candidates(geo, candidates),
        elapsed_seconds=round(time.monotonic() - started, 3),
        input_tokens=sum(t.input_tokens for t in turns),
        output_tokens=sum(t.output_tokens for t in turns),
        error=turns[-1].error,
    )

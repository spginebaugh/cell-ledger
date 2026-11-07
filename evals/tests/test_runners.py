"""The specialist and baseline runners with Claude scripted and GEO faked."""

from __future__ import annotations

import json

import httpx
import pytest

from cell_ledger.geo import GeoClient
from cell_ledger_api.agent.discover import DiscoveryOutput
from evals.baseline import BASELINE_SYSTEM, WEB_SEARCH_TOOL, run_baseline
from evals.records import RunRecord
from evals.specialist import run_specialist, verify_candidates

from .conftest import ScriptedTurns, candidate, conditions, make_case, message, text_message

SEARCH_USE = message(
    [
        {
            "type": "tool_use",
            "id": "tu_1",
            "name": "search_geo",
            "input": {"queries": ["PDAC", "pancreatic cancer"], "since": None},
        }
    ],
    stop="tool_use",
)


def asks() -> DiscoveryOutput:
    return DiscoveryOutput.model_validate(
        {
            "interpretation": "PDAC tumor vs normal pancreas",
            "clarifying_questions": [
                {
                    "question": "Which control: adjacent normal or healthy donor pancreas?",
                    "options": ["adjacent normal", "healthy donor"],
                    "why": "the series differ",
                }
            ],
            "candidates": [candidate("GSE164073")],
            "queries_tried": ["PDAC"],
        }
    )


def proceeds() -> DiscoveryOutput:
    return DiscoveryOutput.model_validate(
        {
            "interpretation": "PDAC tumor vs adjacent normal",
            "candidates": [candidate("GSE164073"), candidate("GSE777777", title="invented")],
            "rejected": [{"gse": "GSE250219", "why": "mouse samples mixed in"}],
            "queries_tried": ["PDAC", "pancreatic cancer"],
        }
    )


async def test_specialist_two_turns_with_scripted_answers(geo_transport_factory=None) -> None:
    from .conftest import geo_transport

    case = make_case(
        expected_action="ask",
        clarification_targets=[["control", "normal"]],
        answers=["adjacent normal"],
    )
    turns = ScriptedTurns(
        SEARCH_USE,
        text_message(asks().model_dump_json(), usage={"input_tokens": 100, "output_tokens": 20}),
        SEARCH_USE,
        text_message(proceeds().model_dump_json()),
    )
    transport = geo_transport(
        search={"PDAC": ["GSE164073"], "pancreatic cancer": ["GSE164073", "GSE250219"]},
        eligible=["GSE164073"],
        existing=["GSE164073", "GSE250219"],
    )
    async with httpx.AsyncClient(transport=transport) as http:
        geo = GeoClient(http)
        rec = await run_specialist(
            case, geo=geo, turn=turns, exa=None, conditions=conditions("specialist", case)
        )

    assert [t.action for t in rec.turns] == ["ask", "proceed"]
    assert rec.turns[0].answers == [] and rec.turns[1].answers == ["adjacent normal"]
    # The second request carried the answers in the user turn.
    assert "adjacent normal" in turns.requests[2]["messages"][0]["content"]
    assert rec.final_action == "proceed"
    assert rec.candidates == ["GSE164073"]  # GSE777777 never came back from GEO
    assert rec.invented == ["GSE777777"]
    assert rec.rejected == ["GSE250219", "GSE777777"]
    assert rec.questions[0]["options"] == ["adjacent normal", "healthy donor"]
    assert rec.seen == ["GSE164073", "GSE250219"]
    assert rec.per_query == {
        "PDAC": ["GSE164073"],
        "pancreatic cancer": ["GSE164073", "GSE250219"],
    }
    assert rec.verification.eligible == ["GSE164073"]
    assert rec.input_tokens == 10 + 100 + 10 + 10 and rec.output_tokens == 5 + 20 + 5 + 5
    assert rec.candidate_details["GSE164073"]["title"] == "title GSE164073"
    assert rec.error is None
    # Round-trips through JSON.
    RunRecord.model_validate_json(rec.model_dump_json())


async def test_specialist_does_not_answer_when_it_did_not_ask() -> None:
    from .conftest import geo_transport

    case = make_case(
        expected_action="ask", clarification_targets=[["control"]], answers=["adjacent normal"]
    )
    turns = ScriptedTurns(SEARCH_USE, text_message(proceeds().model_dump_json()))
    transport = geo_transport(search={"PDAC": ["GSE164073"]}, eligible=["GSE164073"])
    async with httpx.AsyncClient(transport=transport) as http:
        rec = await run_specialist(
            case,
            geo=GeoClient(http),
            turn=turns,
            exa=None,
            conditions=conditions("specialist", case),
        )
    assert len(rec.turns) == 1 and rec.final_action == "proceed"
    assert turns.turns == []  # both scripted turns consumed, no third request


async def test_specialist_refusal_is_an_error_record_not_a_crash() -> None:
    from .conftest import geo_transport

    case = make_case()
    turns = ScriptedTurns(message([], stop="refusal"))
    async with httpx.AsyncClient(transport=geo_transport()) as http:
        rec = await run_specialist(
            case,
            geo=GeoClient(http),
            turn=turns,
            exa=None,
            conditions=conditions("specialist", case),
        )
    assert rec.final_action == "error" and rec.error == "the model declined this request"
    assert rec.candidates == [] and rec.turns[0].output is None


async def test_baseline_verifies_every_named_accession() -> None:
    from .conftest import geo_transport

    case = make_case()
    final = DiscoveryOutput.model_validate(
        {
            "interpretation": "PDAC tumor vs normal",
            "candidates": [
                candidate("GSE164073"),
                candidate("GSE250219"),  # exists, but not eligible
                candidate("GSE999999"),  # does not exist
            ],
            "rejected": [{"gse": "GSE1", "why": "old"}],
        }
    )
    turns = ScriptedTurns(
        message([{"type": "text", "text": "searching..."}], stop="pause_turn"),
        text_message(
            final.model_dump_json(),
            usage={"server_tool_use": {"web_search_requests": 3, "web_fetch_requests": 0}},
        ),
    )
    transport = geo_transport(eligible=["GSE164073"], existing=["GSE164073", "GSE250219"])
    async with httpx.AsyncClient(transport=transport) as http:
        rec = await run_baseline(
            case,
            geo=GeoClient(http),
            turn=turns,
            conditions=conditions("baseline", case, web_search=True),
        )

    first = turns.requests[0]
    assert first["system"] == BASELINE_SYSTEM and first["tools"] == [WEB_SEARCH_TOOL]
    assert first["messages"][0]["content"] == case.prompt
    assert first["output_config"]["format"]["type"] == "json_schema"
    # pause_turn re-sent the conversation with the assistant content appended
    assert turns.requests[1]["messages"][1]["role"] == "assistant"
    assert rec.final_action == "proceed" and len(rec.turns) == 1
    assert rec.candidates == ["GSE164073", "GSE250219", "GSE999999"]
    assert rec.verification.eligible == ["GSE164073"]
    assert rec.verification.exists_only == ["GSE250219"]
    assert rec.verification.missing == ["GSE999999"]
    assert rec.web_search_requests == 3
    assert rec.seen == [] and rec.per_query == {}


async def test_baseline_without_web_search_sends_no_tools() -> None:
    from .conftest import geo_transport

    case = make_case()
    turns = ScriptedTurns(text_message(json.dumps({"interpretation": "x"})))
    async with httpx.AsyncClient(transport=geo_transport()) as http:
        rec = await run_baseline(
            case, geo=GeoClient(http), turn=turns, conditions=conditions("baseline", case)
        )
    assert "tools" not in turns.requests[0]
    assert rec.final_action == "no_results"


async def test_baseline_unreadable_output_is_an_error() -> None:
    from .conftest import geo_transport

    case = make_case()
    turns = ScriptedTurns(text_message("not json"))
    async with httpx.AsyncClient(transport=geo_transport()) as http:
        rec = await run_baseline(
            case, geo=GeoClient(http), turn=turns, conditions=conditions("baseline", case)
        )
    assert rec.final_action == "error" and "unreadable" in (rec.error or "")


async def test_verify_candidates_splits_invalid_from_missing() -> None:
    from .conftest import geo_transport

    async with httpx.AsyncClient(transport=geo_transport(existing=["GSE164073"])) as http:
        v = await verify_candidates(GeoClient(http), ["GSE164073", "GSM5", "GSE42"])
    assert v.invalid == ["GSM5"] and v.exists_only == ["GSE164073"] and v.missing == ["GSE42"]
    assert (await verify_candidates(GeoClient(http), [])).eligible == []


@pytest.mark.parametrize("gses", [[], ["GSE164073"]])
async def test_verify_candidates_is_quiet_on_specialist_output(gses: list[str]) -> None:
    from .conftest import geo_transport

    async with httpx.AsyncClient(transport=geo_transport(eligible=gses, existing=gses)) as http:
        v = await verify_candidates(GeoClient(http), gses)
    assert v.eligible == gses and not v.missing and not v.exists_only

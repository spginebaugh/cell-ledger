"""The discover and design steps with Claude scripted: a TurnRunner that returns canned
messages (so no API key is needed) against the fake GEO host and the real local stack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient

from cell_ledger.geo import DatasetRecord, GeoClient
from cell_ledger_api.agent import Agent, DesignOutput, DiscoveryOutput, discovery_prompt

from .conftest import ApiFactory


def message(content: list[dict[str, Any]], stop: str = "end_turn") -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 1, "output_tokens": 1},
        }
    )


class ScriptedTurns:
    """Returns the scripted messages in order and records every request it saw."""

    def __init__(self, *turns: BetaMessage) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    async def __call__(self, params: dict[str, Any], emit: Any) -> BetaMessage:
        self.requests.append(params)
        await emit({"type": "thinking", "delta": "hmm "})
        return self.turns.pop(0)


def events(resp: httpx.Response) -> list[dict[str, Any]]:
    out = []
    for line in resp.text.splitlines():
        if line.startswith("data: "):
            out.append(json.loads(line[6:]))
    return out


def test_unconfigured_agent_is_503(client: TestClient) -> None:
    sid = client.post("/api/sessions").json()["id"]
    assert client.get("/api/agent/types").json()["available"] is False
    r = client.post(f"/api/sessions/{sid}/discover", json={"question": "is IL17A up in psoriasis?"})
    assert r.status_code == 503


def test_discover_streams_tools_and_result(
    api: ApiFactory, geo_transport: httpx.MockTransport
) -> None:
    final = DiscoveryOutput.model_validate(
        {
            "interpretation": "psoriasis lesional vs healthy skin",
            "genes": ["IL17A"],
            "clarifying_questions": [
                {
                    "question": "Which control: healthy or non-lesional skin?",
                    "options": ["healthy skin", "non-lesional skin"],
                    "why": "some series only have one of the two",
                }
            ],
            "candidates": [
                {
                    "gse": "GSE100001",
                    "title": "Drug X in PANC-1 cells",
                    "n_samples": 2,
                    "why": "has both arms",
                    "case_hint": "lesional",
                    "control_hint": "healthy",
                    "concerns": [],
                },
                {  # never came back from GEO in this run -> must be dropped
                    "gse": "GSE999999",
                    "title": "made up",
                    "n_samples": 10,
                    "why": "I remember it",
                    "case_hint": "x",
                    "control_hint": "y",
                    "concerns": [],
                },
            ],
            "queries_tried": ["psoriasis skin RNA-seq"],
        }
    )
    turns = ScriptedTurns(
        message(
            [
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "verify_geo_series",
                    "input": {"gses": ["GSE100001"]},
                }
            ],
            stop="tool_use",
        ),
        message([{"type": "text", "text": final.model_dump_json()}]),
    )
    with api(turn=turns) as c:
        assert c.get("/api/agent/types").json()["available"] is True
        sid = c.post("/api/sessions").json()["id"]
        with c.stream(
            "POST", f"/api/sessions/{sid}/discover", json={"question": "is IL17A up in psoriasis?"}
        ) as r:
            assert r.status_code == 200
            assert r.headers["content-type"].startswith("text/event-stream")
            r.read()
            evs = events(r)
        kinds = [e["type"] for e in evs]
        assert kinds[0] == "thinking" and kinds[-1] == "done"
        tool = next(e for e in evs if e["type"] == "tool")
        assert tool["name"] == "verify_geo_series" and "verified 1" in tool["summary"]
        result = next(e for e in evs if e["type"] == "result")["data"]
        assert result["genes"] == ["IL17A"]
        assert result["clarifying_questions"][0]["options"] == ["healthy skin", "non-lesional skin"]
        # The fake GEO host answers esearch with no ids, so verification found nothing and
        # neither accession is confirmed: both are rejected, none invented.
        assert result["candidates"] == []
        assert {r["gse"] for r in result["rejected"]} == {"GSE100001", "GSE999999"}
        # The trace is the code's record of the run, not the model's.
        trace = result["trace"]
        assert trace["turns"] == 2 and trace["seen"] == []
        assert sorted(trace["invented"]) == ["GSE100001", "GSE999999"]
        assert [c["tool"] for c in trace["calls"]] == ["verify_geo_series"]
        assert trace["calls"][0]["ineligible"] == ["GSE100001"]
        assert trace["usage"] == {
            "input_tokens": 2,
            "output_tokens": 2,
            "cache_read_input_tokens": 0,
            "cache_creation_input_tokens": 0,
        }
        # The question was recorded on the session.
        assert c.get(f"/api/sessions/{sid}").json()["question"] == "is IL17A up in psoriasis?"
        # The second request carried the tool result back to Claude.
        assert turns.requests[1]["messages"][-1]["content"][0]["type"] == "tool_result"
        assert turns.requests[0]["output_config"]["format"]["type"] == "json_schema"
        # Claude is held to the output schema; the trace is not part of it.
        schema = turns.requests[0]["output_config"]["format"]["schema"]
        assert "trace" not in schema["properties"] and "out_of_scope" in schema["properties"]


def test_discover_rejects_too_many_answers(api: ApiFactory) -> None:
    with api(turn=ScriptedTurns()) as c:
        sid = c.post("/api/sessions").json()["id"]
        r = c.post(f"/api/sessions/{sid}/discover", json={"question": "q?", "answers": ["a"] * 11})
        assert r.status_code == 422


ESUMMARY = json.loads(
    (
        Path(__file__).parents[3] / "packages/core/tests/fixtures/geo/esummary_two_series.json"
    ).read_text()
)


def _geo_two_series() -> httpx.MockTransport:
    """A GEO that returns GSE164073 for a PDAC query and both series for a broader one."""

    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            term = request.url.params["term"]
            ids = ["200164073"] if term.startswith("(PDAC)") else ["200164073", "200250219"]
            return httpx.Response(
                200, json={"esearchresult": {"count": str(len(ids)), "idlist": ids}}
            )
        return httpx.Response(200, json=ESUMMARY)

    return httpx.MockTransport(handle)


async def test_discover_trace_records_queries_answers_and_scope() -> None:
    final = DiscoveryOutput.model_validate(
        {
            "interpretation": "PDAC tumor vs normal pancreas",
            "out_of_scope": "contradiction: candidates attached",
            "candidates": [
                {
                    "gse": "GSE164073",
                    "title": "t",
                    "n_samples": 6,
                    "why": "fits",
                    "case_hint": "tumor",
                    "control_hint": "normal",
                }
            ],
            "rejected": [{"gse": "GSE250219", "why": "mouse samples mixed in"}],
            "queries_tried": ["PDAC", "pancreatic cancer"],
        }
    )
    turns = ScriptedTurns(
        message(
            [
                {
                    "type": "tool_use",
                    "id": "tu_1",
                    "name": "search_geo",
                    "input": {"queries": ["PDAC", "pancreatic cancer"], "since": None},
                }
            ],
            stop="tool_use",
        ),
        message([{"type": "text", "text": final.model_dump_json()}]),
    )

    async def emit(_: Any) -> None:
        pass

    async with httpx.AsyncClient(transport=_geo_two_series()) as http:
        agent = Agent(GeoClient(http), turn=turns)
        result = await agent.discover(
            "Is KRT19 up in PDAC?", emit, answers=["tumor vs adjacent normal", ""]
        )

    # The answers travel in the user turn in one fixed format, blank ones dropped.
    prompt = turns.requests[0]["messages"][0]["content"]
    assert prompt == discovery_prompt("Is KRT19 up in PDAC?", ["tumor vs adjacent normal"])
    assert prompt.startswith("Is KRT19 up in PDAC?\n\nClarifications from the user")
    assert prompt.endswith("- tumor vs adjacent normal")
    # Per-query accessions come from GEO's matched_queries, not from the model.
    (call,) = result.trace.calls
    assert call.tool == "search_geo" and call.error is None
    assert {q.query: q.gses for q in call.queries} == {
        "PDAC": ["GSE164073"],
        "pancreatic cancer": ["GSE164073", "GSE250219"],
    }
    assert call.confirmed == call.shown == ["GSE164073", "GSE250219"]
    assert result.trace.seen == ["GSE164073", "GSE250219"] and result.trace.invented == []
    assert [c.gse for c in result.candidates] == ["GSE164073"]
    # A scope verdict cannot coexist with confirmed candidates.
    assert result.out_of_scope is None
    assert result.trace.elapsed_seconds >= 0 and result.trace.turns == 2


RECORD = DatasetRecord.model_validate(
    {
        "gse": "GSE100001",
        "status": "ready",
        "title": "Psoriasis skin",
        "samples": [
            {
                "gsm": f"GSM{i}",
                "title": f"{kind}_{i}",
                "source_name": "skin biopsy",
                "organism": "Homo sapiens",
                "library_strategy": "RNA-Seq",
                "characteristics": [f"tissue: {kind} skin", f"patient: P{i % 3}"],
                "in_counts": True,
            }
            for i, kind in enumerate(["lesional"] * 3 + ["healthy"] * 3, start=1)
        ],
        "n_eligible": 6,
    }
)


def labels(evidence_for: dict[str, list[str]]) -> DesignOutput:
    return DesignOutput.model_validate(
        {
            "samples": [
                {
                    "gsm": s.gsm,
                    "group": "case" if "lesional" in s.title else "control",
                    "tissue": "skin",
                    "donor": s.characteristics[1].split(": ")[1],
                    "evidence": evidence_for.get(s.gsm, [s.characteristics[0]]),
                    "confidence": 0.95,
                }
                for s in RECORD.samples
            ],
            "contrast": {
                "name": "Lesional vs Healthy",
                "case_label": "psoriasis lesional skin",
                "control_label": "healthy skin",
                "case_gsms": ["GSM1", "GSM2", "GSM3"],
                "control_gsms": ["GSM4", "GSM5", "GSM6"],
                "blocking": None,
                "rationale": "tissue field says it",
                "confidence": 0.9,
            },
            "decisions": ["pooled all patients: the record gives no reason to separate them"],
            "notes": "clean",
        }
    )


def test_compile_enforces_verbatim_evidence() -> None:
    proposal, errors = Agent.compile(RECORD, labels({}), ["IL17A"])
    assert proposal is not None and errors == []
    d = proposal.design
    assert d.samplesheet.gse == "GSE100001" and len(d.samplesheet.samples) == 6
    (c,) = d.contrasts
    # Confirmed, not proposed: nobody reviews it before the pipeline runs it.
    assert c.name == "lesional_vs_healthy" and c.status == "confirmed"
    assert proposal.problems == [] and proposal.decisions[0].startswith("pooled all patients")
    assert d.genes == ["IL17A"]

    bad, errors = Agent.compile(RECORD, labels({"GSM1": ["tissue: lesion skin"]}), [])
    # GSM1 is dropped for fabricated evidence; the contrast then names a GSM not in the sheet,
    # which is a problem, which makes the pipeline skip the dataset.
    assert any("GSM1" in e and "evidence" in e for e in errors)
    assert bad is not None and "GSM1" in str(bad.problems)

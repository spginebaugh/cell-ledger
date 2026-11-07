"""The discover and design steps with Claude scripted: a TurnRunner that returns canned
messages (so no API key is needed) against the fake GEO host and the real local stack."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient
from pydantic import ValidationError

from cell_ledger.geo import DatasetRecord, GeoClient
from cell_ledger_api.agent.design import (
    Designer,
    DesignOutput,
    DesignRequest,
    compile_design,
    record_donor,
    record_text,
)
from cell_ledger_api.agent.discover import Discoverer, DiscoveryOutput, discovery_prompt
from cell_ledger_api.agent.llm import AgentUnavailable, quiet

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
        assert turns.requests[0]["cache_control"] == {"type": "ephemeral"}
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
        result = await Discoverer(GeoClient(http), turn=turns).discover(
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
    proposal, errors = compile_design(RECORD, labels({}), ["IL17A"])
    assert proposal is not None and errors == []
    d = proposal.design
    assert d.samplesheet.gse == "GSE100001" and len(d.samplesheet.samples) == 6
    (c,) = d.contrasts
    # Confirmed, not proposed: nobody reviews it before the pipeline runs it.
    assert c.name == "lesional_vs_healthy" and c.status == "confirmed"
    assert proposal.problems == [] and proposal.decisions[0].startswith("pooled all patients")
    assert d.genes == ["IL17A"]

    bad, errors = compile_design(RECORD, labels({"GSM1": ["tissue: lesion skin"]}), [])
    # GSM1 is dropped for fabricated evidence; the contrast then names a GSM not in the sheet,
    # which is a problem, which makes the pipeline skip the dataset.
    assert any("GSM1" in e and "evidence" in e for e in errors)
    assert bad is not None and "GSM1" in str(bad.problems)


def test_compile_pairs_on_donor_when_the_model_left_it_out() -> None:
    # Every donor (P0, P1, P2) gives one sample to each arm; the model set no blocking.
    proposal, _ = compile_design(RECORD, labels({}), [])
    assert proposal is not None
    assert proposal.design.contrasts[0].blocking == "donor"
    assert any("Paired by donor: 3 donors" in d for d in proposal.decisions)

    # With fewer than three donors in both arms the fit stays unpaired and nothing is added.
    # (The record must not state the patient either, or the donor is taken from it.)
    unstated = RECORD.model_copy(deep=True)
    for rec in unstated.samples:
        rec.characteristics = [c for c in rec.characteristics if not c.startswith("patient")]
    out = labels({})
    for s in out.samples:
        if s.donor == "P0":
            s.donor = None
    proposal, _ = compile_design(unstated, out, [])
    assert proposal is not None and proposal.design.contrasts[0].blocking is None
    assert not any("Paired by donor" in d for d in proposal.decisions)


def test_compile_takes_the_donor_from_the_record_when_the_model_leaves_it_empty() -> None:
    # RECORD states "patient: P1" etc.; the model filled no donor and set no blocking.
    out = labels({})
    for s in out.samples:
        s.donor = None
    proposal, _ = compile_design(RECORD, out, [])
    assert proposal is not None
    donors = {s.gsm: s.donor for s in proposal.design.samplesheet.samples}
    assert donors["GSM1"] == "P1" and donors["GSM4"] == "P1"
    assert proposal.design.contrasts[0].blocking == "donor"


def test_record_donor_reads_only_id_fields() -> None:
    assert record_donor({"patient id": "10004", "diagnosis": "psoriasis"}) == "10004"
    assert record_donor({"Patient": "1"}) == "1"
    assert record_donor({"Subject_ID": "S7"}) == "S7"
    # A diagnosis that happens to start with "patient" is not an identifier.
    assert record_donor({"patient's condition": "AD", "skin type": "lesional"}) is None
    assert record_donor({"patient id": "  "}) is None


def test_blocking_only_accepts_the_donor_column() -> None:
    # Anything but a sample-sheet column would be silently fitted unpaired downstream.
    data = labels({}).model_dump()
    data["contrast"]["blocking"] = "patient id"
    with pytest.raises(ValidationError):
        DesignOutput.model_validate(data)
    data["contrast"]["blocking"] = "donor"
    assert DesignOutput.model_validate(data).contrast.blocking == "donor"


def _tool_use(id_: str, name: str, input_: dict[str, Any]) -> dict[str, Any]:
    return {"type": "tool_use", "id": id_, "name": name, "input": input_}


async def test_failing_tools_become_tool_errors_not_a_dead_agent() -> None:
    """Bad input, an unknown tool and a GEO outage each come back to Claude as an error
    result, land in the trace, and the run still finishes."""

    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("GEO is down", request=request)

    final = DiscoveryOutput(interpretation="x vs y")
    turns = ScriptedTurns(
        message(
            [
                _tool_use("tu_1", "search_geo", {"queries": [" "], "since": None}),
                _tool_use("tu_2", "verify_geo_series", {"gses": ["not-an-accession"]}),
                _tool_use("tu_3", "drop_tables", {}),
                _tool_use("tu_4", "search_geo", {"queries": ["psoriasis"], "since": None}),
            ],
            stop="tool_use",
        ),
        message([{"type": "text", "text": final.model_dump_json()}]),
    )
    emitted: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        emitted.append(event)

    async with httpx.AsyncClient(transport=httpx.MockTransport(down)) as http:
        result = await Discoverer(GeoClient(http), turn=turns).discover("x vs y?", emit)

    sent = turns.requests[1]["messages"][-1]["content"]
    assert [r["is_error"] for r in sent] == [True, True, True, True]
    assert sent[0]["content"] == "error: no queries given"
    assert sent[1]["content"].startswith("error: not GEO series accessions")
    assert sent[2]["content"] == "error: unknown tool drop_tables"
    assert sent[3]["content"].startswith("error: ConnectError: GEO is down")
    assert [e["summary"] for e in emitted if e["type"] == "tool"] == [
        "search_geo: no queries",
        "verify: invalid accession",
        "unknown tool drop_tables",
        "search_geo failed",
    ]
    calls = result.trace.calls
    assert [c.tool for c in calls] == [
        "search_geo",
        "verify_geo_series",
        "drop_tables",
        "search_geo",
    ]
    assert all(c.error and not c.confirmed for c in calls)
    assert calls[3].error == "ConnectError: GEO is down"


def test_fingerprint_covers_tools_model_and_effort() -> None:
    geo = GeoClient(httpx.AsyncClient())
    base = Discoverer(geo)
    assert base.fingerprint() == Discoverer(geo, turn=ScriptedTurns()).fingerprint()
    assert [t["name"] for t in base.tool_definitions()] == [
        "search_geo",
        "verify_geo_series",
        "inspect_series",
    ]
    with_web = Discoverer(geo, exa=object())  # type: ignore[arg-type]
    assert [t["name"] for t in with_web.tool_definitions()][-1] == "find_geo_series_on_web"
    assert all(t["strict"] for t in with_web.tool_definitions())
    others = {
        with_web.fingerprint(),
        Discoverer(geo, model="claude-sonnet-5-5").fingerprint(),
        Discoverer(geo, effort="high").fingerprint(),
    }
    assert base.fingerprint() not in others and len(others) == 3


async def test_design_retries_once_with_the_validator_errors() -> None:
    turns = ScriptedTurns(
        message([{"type": "text", "text": labels({"GSM1": ["not in record"]}).model_dump_json()}]),
        message([{"type": "text", "text": labels({}).model_dump_json()}]),
    )
    emitted: list[dict[str, Any]] = []

    async def emit(event: dict[str, Any]) -> None:
        emitted.append(event)

    req = DesignRequest(question="Is IL17A up in psoriasis?", genes=["IL17A"])
    proposal = await Designer(turn=turns).design(RECORD, req, emit)

    assert proposal.attempts == 2 and proposal.validation_errors == []
    assert proposal.problems == [] and proposal.design.genes == ["IL17A"]
    validate = next(e for e in emitted if e["type"] == "tool")
    assert validate["name"] == "validate" and "rejected" in validate["summary"]
    retry = turns.requests[1]["messages"]
    assert [m["role"] for m in retry] == ["user", "assistant", "user"]
    assert retry[2]["content"].startswith("The validator rejected these labels")
    assert "GSM1" in retry[2]["content"]
    assert turns.requests[0]["output_config"]["format"]["type"] == "json_schema"
    assert "tools" not in turns.requests[0]


async def test_design_gives_up_on_unreadable_output_and_refusals() -> None:
    req = DesignRequest(question="Is IL17A up in psoriasis?")
    garbled = ScriptedTurns(message([{"type": "text", "text": "{not json"}]))
    with pytest.raises(AgentUnavailable, match="could not build a valid design: unreadable"):
        await Designer(turn=garbled).design(RECORD, req, quiet)
    refused = ScriptedTurns(message([], stop="refusal"))
    with pytest.raises(AgentUnavailable, match="declined"):
        await Designer(turn=refused).design(RECORD, req, quiet)
    with pytest.raises(AgentUnavailable, match="not configured"):
        await Designer().design(RECORD, req, quiet)


def _excluding(**reasons: list[str]) -> DatasetRecord:
    """RECORD with the named samples excluded (``GSM6=["not_in_counts"]`` etc.)."""
    record = RECORD.model_copy(deep=True)
    for s in record.samples:
        if s.gsm in reasons:
            s.exclusions = reasons[s.gsm]  # type: ignore[assignment]
            s.in_counts = "not_in_counts" not in reasons[s.gsm]
    return record


def test_compile_rejects_samples_claude_was_never_shown() -> None:
    record = _excluding(GSM3=["not_human"], GSM6=["not_in_counts"])
    # The prompt and the validator agree on which samples exist.
    shown = {s["gsm"] for s in json.loads(record_text(record))["samples"]}
    assert shown == {"GSM1", "GSM2", "GSM4", "GSM5"}

    proposal, errors = compile_design(record, labels({}), [])
    assert errors == [
        "GSM3: excluded from analysis (not_human)",
        "GSM6: excluded from analysis (not_in_counts)",
    ]
    assert proposal is not None
    assert {s.gsm for s in proposal.design.samplesheet.samples} == shown
    # The contrast still names them, so it must not run.
    assert any("GSM3" in p and "GSM6" in p for p in proposal.problems)


async def test_design_retry_tells_claude_which_samples_are_excluded() -> None:
    record = _excluding(GSM3=["not_human"])
    fixed = labels({}).model_copy(deep=True)
    fixed.samples = [s for s in fixed.samples if s.gsm != "GSM3"]
    fixed.contrast.case_gsms = ["GSM1", "GSM2"]
    turns = ScriptedTurns(
        message([{"type": "text", "text": labels({}).model_dump_json()}]),
        message([{"type": "text", "text": fixed.model_dump_json()}]),
    )
    proposal = await Designer(turn=turns).design(record, DesignRequest(question="q??"), quiet)
    retry = turns.requests[1]["messages"][2]["content"]
    assert "GSM3: excluded from analysis (not_human)" in retry
    assert "leave out any sample it says is excluded" in retry
    assert proposal.attempts == 2 and proposal.validation_errors == []
    assert any("fewer than 3" in p for p in proposal.problems)


def _with_unknown_sample() -> DesignOutput:
    """A design whose one rejected label is not in any arm: it compiles with no problems."""
    out = labels({}).model_copy(deep=True)
    out.samples.append(out.samples[0].model_copy(update={"gsm": "GSM99"}))
    return out


async def test_unreadable_correction_keeps_the_first_design_and_says_so() -> None:
    turns = ScriptedTurns(
        message([{"type": "text", "text": _with_unknown_sample().model_dump_json()}]),
        message([{"type": "text", "text": "{not json"}]),
    )
    proposal = await Designer(turn=turns).design(RECORD, DesignRequest(question="q??"), quiet)
    assert proposal.attempts == 2 and len(turns.requests) == 2
    assert proposal.validation_errors == ["GSM99: not a sample of GSE100001"]
    (note,) = proposal.qualifications
    assert "attempt 2) was not used because it was unreadable" in note
    assert "attempt 1's design, with 1 label(s) rejected" in note
    assert proposal.problems == []  # it runs, as any design with only these errors would


async def test_uncompilable_correction_keeps_the_first_design_and_says_so() -> None:
    nothing = labels({}).model_copy(deep=True)
    for i, s in enumerate(nothing.samples):
        s.gsm = f"GSM9{i}"
    turns = ScriptedTurns(
        message([{"type": "text", "text": _with_unknown_sample().model_dump_json()}]),
        message([{"type": "text", "text": nothing.model_dump_json()}]),
    )
    proposal = await Designer(turn=turns).design(RECORD, DesignRequest(question="q??"), quiet)
    assert proposal.attempts == 2
    assert proposal.validation_errors == ["GSM99: not a sample of GSE100001"]
    (note,) = proposal.qualifications
    assert "was not used because it did not compile: GSM90: not a sample" in note
    assert "attempt 1's design" in note

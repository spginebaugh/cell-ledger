"""The discover and design steps with Claude scripted: a TurnRunner that returns canned
messages (so no API key is needed) against the fake GEO host and the real local stack."""

from __future__ import annotations

import json
from typing import Any

import httpx
from anthropic.types.beta import BetaMessage
from fastapi.testclient import TestClient

from cell_ledger.geo import DatasetRecord
from cell_ledger_api.agent import Agent, DesignOutput, DiscoveryResult

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
    final = DiscoveryResult.model_validate(
        {
            "interpretation": "psoriasis lesional vs healthy skin",
            "genes": ["IL17A"],
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
        # The fake GEO host answers esearch with no ids, so verification found nothing and
        # neither accession is confirmed: both are rejected, none invented.
        assert result["candidates"] == []
        assert {r["gse"] for r in result["rejected"]} == {"GSE100001", "GSE999999"}
        # The question was recorded on the session.
        assert c.get(f"/api/sessions/{sid}").json()["question"] == "is IL17A up in psoriasis?"
        # The second request carried the tool result back to Claude.
        assert turns.requests[1]["messages"][-1]["content"][0]["type"] == "tool_result"
        assert turns.requests[0]["output_config"]["format"]["type"] == "json_schema"


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

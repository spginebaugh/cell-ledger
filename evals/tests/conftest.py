"""Scripted Claude turns and a fake GEO host, so the eval runners run without credentials."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from anthropic.types.beta import BetaMessage

from evals.cases import Case
from evals.records import Conditions

ESUMMARY = json.loads(
    (
        Path(__file__).parents[2] / "packages/core/tests/fixtures/geo/esummary_two_series.json"
    ).read_text()
)
# uid -> accession in that fixture
UIDS = {"GSE164073": "200164073", "GSE250219": "200250219"}


def message(
    content: list[dict[str, Any]], stop: str = "end_turn", usage: dict[str, Any] | None = None
) -> BetaMessage:
    return BetaMessage.model_validate(
        {
            "id": "msg_1",
            "type": "message",
            "role": "assistant",
            "model": "claude-opus-5-5",
            "content": content,
            "stop_reason": stop,
            "stop_sequence": None,
            "usage": {"input_tokens": 10, "output_tokens": 5, **(usage or {})},
        }
    )


def text_message(payload: Any, **kw: Any) -> BetaMessage:
    body = payload if isinstance(payload, str) else json.dumps(payload)
    return message([{"type": "text", "text": body}], **kw)


class ScriptedTurns:
    def __init__(self, *turns: BetaMessage) -> None:
        self.turns = list(turns)
        self.requests: list[dict[str, Any]] = []

    async def __call__(self, params: dict[str, Any], emit: Any) -> BetaMessage:
        self.requests.append(params)
        if not self.turns:
            raise AssertionError("no scripted turn left")
        return self.turns.pop(0)


def geo_transport(
    *,
    search: dict[str, list[str]] | None = None,
    eligible: list[str] = (),  # type: ignore[assignment]
    existing: list[str] = (),  # type: ignore[assignment]
    calls: list[httpx.Request] | None = None,
) -> httpx.MockTransport:
    """esearch terms are told apart by shape: ``[ACCN]`` with the counts filter is a verify,
    ``[ACCN]`` without it an existence check, anything else a keyword search."""
    search = search or {}

    def handle(request: httpx.Request) -> httpx.Response:
        if calls is not None:
            calls.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            params = (
                request.url.params
                if request.method == "GET"
                else httpx.QueryParams(request.content.decode())
            )
            term = params["term"]
            if "[ACCN]" in term:
                wanted = eligible if "rnaseq counts" in term else existing
                ids = [UIDS[g] for g in wanted if f"{g}[ACCN]" in term]
            else:
                query = term.split(") AND ", 1)[0].removeprefix("(")
                ids = [UIDS[g] for g in search.get(query, [])]
            return httpx.Response(
                200, json={"esearchresult": {"count": str(len(ids)), "idlist": ids}}
            )
        assert request.url.path.endswith("esummary.fcgi")
        return httpx.Response(200, json=ESUMMARY)

    return httpx.MockTransport(handle)


def make_case(**overrides: Any) -> Case:
    base: dict[str, Any] = {
        "id": "pdac_tumor_vs_normal",
        "prompt": "Which genes differ between PDAC tumor and normal pancreas?",
        "expected_action": "proceed",
        "pool": {
            "GSE164073": {
                "relevant": True,
                "eligible": True,
                "rationale": "fits",
                "reviewed_by": "t",
            },
            "GSE250219": {
                "relevant": True,
                "eligible": True,
                "rationale": "fits",
                "reviewed_by": "t",
            },
        },
        "status": "reviewed",
        "reviewed_by": "t",
    }
    base.update(overrides)
    return Case.model_validate(base)


def conditions(system: str, case: Case, **overrides: Any) -> Conditions:
    base: dict[str, Any] = {
        "system": system,
        "model": "claude-opus-5-5",
        "effort": "medium",
        "fingerprint": "f" * 64,
        "web_search": False,
        "code_revision": "abc",
        "dirty": False,
        "geo_cache": "/tmp/cache",
        "case_sha256": case.digest(),
        "suite_sha256": "s" * 64,
        "run_id": "run1",
        "started_at": "2026-11-07T00:00:00+00:00",
    }
    base.update(overrides)
    return Conditions.model_validate(base)


def candidate(gse: str, **kw: Any) -> dict[str, Any]:
    return {
        "gse": gse,
        "title": kw.get("title", f"title {gse}"),
        "n_samples": 6,
        "why": kw.get("why", "has both arms"),
        "case_hint": "tumor",
        "control_hint": "normal",
        "concerns": [],
    }


@pytest.fixture
def quiet():
    async def emit(_: Any) -> None:
        pass

    return emit

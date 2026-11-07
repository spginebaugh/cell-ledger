"""Exa discovery: nominations come from Exa, eligibility comes from GEO."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from cell_ledger.geo import GeoClient
from cell_ledger_api.discovery import (
    FIND_SERIES_TOOL,
    OBJECTIVE_DESCRIPTION,
    find_series_on_web,
)
from cell_ledger_api.main import create_app

from .conftest import local_settings

ESUMMARY = json.loads(
    (
        Path(__file__).parents[3] / "packages/core/tests/fixtures/geo/esummary_two_series.json"
    ).read_text()
)


class FakeExa:
    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def search(self, query: str, **kwargs: Any) -> Any:
        self.calls.append((query, kwargs))
        return self.response


def _response() -> Any:
    return SimpleNamespace(
        output=SimpleNamespace(
            content={
                "series": [
                    {
                        "gse": "GSE164073",
                        "url": "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE164073",
                    },
                    {"gse": "not an accession", "url": "https://x"},
                ]
            }
        ),
        results=[
            SimpleNamespace(
                url="https://paper.example/article",
                title="Corneal infection",
                highlights=["Data are in GEO under GSE164073 and GSE999999."],
            )
        ],
        cost_dollars=SimpleNamespace(total=0.012),
    )


def _geo_transport(eligible_uids: list[str]) -> httpx.MockTransport:
    def handle(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("esearch.fcgi"):
            count = str(len(eligible_uids))
            return httpx.Response(
                200, json={"esearchresult": {"count": count, "idlist": eligible_uids}}
            )
        return httpx.Response(200, json=ESUMMARY)

    return httpx.MockTransport(handle)


async def test_only_geo_verified_series_survive() -> None:
    exa = FakeExa(_response())
    async with httpx.AsyncClient(transport=_geo_transport(["200164073"])) as http:
        result = await find_series_on_web(exa, GeoClient(http), "PDAC drug response", "find series")

    assert result.nominated == ["GSE164073", "GSE999999"]
    assert [v.hit.gse for v in result.verified] == ["GSE164073"]
    assert result.verified[0].found_at == [
        "https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE164073",
        "https://paper.example/article",
    ]
    assert result.rejected == ["GSE999999"]
    assert result.exa_cost_dollars == pytest.approx(0.012)


async def test_exa_request_follows_recommended_shape() -> None:
    exa = FakeExa(SimpleNamespace(output=None, results=[], cost_dollars=None))
    async with httpx.AsyncClient(transport=_geo_transport([])) as http:
        result = await find_series_on_web(exa, GeoClient(http), "q", "the objective")

    ((query, kw),) = exa.calls
    assert query == "q"
    assert kw["type"] == "auto" and kw["objective"] == "the objective"
    assert kw["contents"] == {"highlights": True}
    assert "output_schema" in kw and "system_prompt" in kw
    assert not {"num_results", "include_domains", "category"} & kw.keys()
    assert result.nominated == [] and result.verified == []


def test_tool_requires_objective_with_exa_wording() -> None:
    schema = FIND_SERIES_TOOL["input_schema"]
    assert schema["required"] == ["query", "objective"]
    assert schema["properties"]["objective"]["description"] == OBJECTIVE_DESCRIPTION
    # The agent sends it with strict: true; the API rejects a strict object schema without this.
    assert schema["additionalProperties"] is False


def _client(tmp_path: Path, exa: Any) -> TestClient:
    cfg = local_settings(data_dir=tmp_path)
    return TestClient(create_app(cfg, transport=_geo_transport(["200164073"]), exa=exa))


def test_web_search_and_verify_endpoints(tmp_path: Path) -> None:
    with _client(tmp_path, FakeExa(_response())) as c:
        r = c.post("/api/geo/web-search", json={"query": "q", "objective": "o"})
        assert r.status_code == 200 and r.json()["rejected"] == ["GSE999999"]

        v = c.post("/api/geo/verify", json={"gses": ["GSE164073", "GSE1"]})
        assert v.status_code == 200
        assert v.json()["ineligible"] == ["GSE1"]
        assert c.post("/api/geo/verify", json={"gses": ["GSM1"]}).status_code == 422


def test_web_search_without_exa_key_is_503(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("EXA_API_KEY", raising=False)
    monkeypatch.delenv("CELL_LEDGER_EXA_API_KEY", raising=False)
    with _client(tmp_path, None) as c:
        r = c.post("/api/geo/web-search", json={"query": "q", "objective": "o"})
        assert r.status_code == 503

import json
from pathlib import Path
from urllib.parse import parse_qs

import httpx
import pytest

from cell_ledger.geo import ELIGIBILITY, GeoClient, SearchResult

ESUMMARY = json.loads((Path(__file__).parent / "fixtures/geo/esummary_two_series.json").read_text())

# uid 200164073 = GSE164073 (human only), 200250219 = GSE250219 (mouse + human)
ESEARCH_IDS = {"PDAC": ["200164073"], "pancreatic cancer": ["200164073", "200250219"]}


def _handler(calls: list[httpx.Request]):
    def handle(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        if request.url.path.endswith("esearch.fcgi"):
            query = request.url.params["term"].split(") AND ", 1)[0].removeprefix("(")
            ids = ESEARCH_IDS.get(query, [])
            return httpx.Response(
                200, json={"esearchresult": {"count": str(len(ids) * 10), "idlist": ids}}
            )
        assert request.url.path.endswith("esummary.fcgi")
        return httpx.Response(200, json=ESUMMARY)

    return handle


async def _search(calls: list[httpx.Request], *queries: str, **kw: object) -> SearchResult:
    async with httpx.AsyncClient(transport=httpx.MockTransport(_handler(calls))) as http:
        return await GeoClient(http, api_key="k").search_series(list(queries), **kw)  # type: ignore[arg-type]


async def test_unions_queries_and_records_which_matched() -> None:
    result = await _search([], "PDAC", "pancreatic cancer", "PDAC ")

    assert [q.query for q in result.queries] == ["PDAC", "pancreatic cancer"]  # deduped
    assert [h.gse for h in result.hits] == ["GSE164073", "GSE250219"]
    assert result.hits[0].matched_queries == ["PDAC", "pancreatic cancer"]
    assert result.hits[1].matched_queries == ["pancreatic cancer"]
    assert (result.queries[1].total, result.queries[1].returned) == (20, 2)


async def test_every_query_carries_eligibility_filter_and_api_key() -> None:
    calls: list[httpx.Request] = []
    await _search(calls, "PDAC", since=2018)

    term = calls[0].url.params["term"]
    assert term.startswith("(PDAC) AND " + ELIGIBILITY)
    assert '"2018/01/01"[PDAT]' in term
    assert calls[0].url.params["api_key"] == "k"
    form = parse_qs(calls[1].content.decode())
    assert form["api_key"] == ["k"] and form["id"] == ["200164073"]


async def test_flags_mixed_organism_series() -> None:
    human, mixed = (await _search([], "pancreatic cancer")).hits
    assert not human.mixed_organism and human.n_samples == 18
    assert human.published is not None and human.published.year == 2020
    assert mixed.mixed_organism and mixed.taxa == ["Mus musculus", "Homo sapiens"]


async def test_no_hits_skips_summary_call() -> None:
    calls: list[httpx.Request] = []
    result = await _search(calls, "nothing matches")
    assert result.hits == [] and result.queries[0].total == 0
    assert len(calls) == 1


async def test_retries_rate_limit_response() -> None:
    attempts = 0

    def handle(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(429)
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
        result = await GeoClient(http, retry_delay=0).search_series(["x"])
    assert attempts == 2 and result.hits == []


async def test_rejects_empty_queries() -> None:
    with pytest.raises(ValueError):
        await _search([], " ", "")

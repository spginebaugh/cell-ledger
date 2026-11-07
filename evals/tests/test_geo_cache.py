from types import SimpleNamespace

import httpx

from evals.geo_cache import CachedExa, CachedGeoClient

from .conftest import geo_transport


async def test_search_verify_and_exists_hit_the_cache_on_repeat(tmp_path) -> None:
    calls: list[httpx.Request] = []
    transport = geo_transport(
        search={"PDAC": ["GSE164073"]},
        eligible=["GSE164073"],
        existing=["GSE164073", "GSE250219"],
        calls=calls,
    )
    async with httpx.AsyncClient(transport=transport) as http:
        geo = CachedGeoClient(http, tmp_path)
        first = await geo.search_series(["PDAC"], limit_per_query=25)
        n = len(calls)
        again = await geo.search_series(["PDAC"], limit_per_query=25)
        assert again == first and len(calls) == n
        assert (await geo.verify_series(["GSE164073", "GSE250219"])).ineligible == ["GSE250219"]
        n = len(calls)
        assert (await geo.verify_series(["gse250219", "GSE164073"])).ineligible == ["GSE250219"]
        assert len(calls) == n, "order and case do not matter for the cache key"
        assert await geo.exists_series(["GSE250219"]) == ["GSE250219"]
        n = len(calls)
        assert await geo.exists_series(["GSE250219"]) == ["GSE250219"]
        assert len(calls) == n
        assert geo.hits == 3 and geo.misses == 3
        # A different limit is a different request.
        await geo.search_series(["PDAC"], limit_per_query=5)
        assert geo.misses == 4


async def test_cached_exa_round_trips_the_fields_discovery_reads(tmp_path) -> None:
    class Exa:
        calls = 0

        async def search(self, query, **kwargs):
            self.calls += 1
            return SimpleNamespace(
                output=SimpleNamespace(content={"series": [{"gse": "GSE1", "url": "u"}]}),
                results=[SimpleNamespace(url="u", title="t", highlights=["GSE1 here"])],
                cost_dollars=SimpleNamespace(total=0.01),
            )

    exa = Exa()
    cached = CachedExa(exa, tmp_path)
    a = await cached.search("q", objective="o")
    b = await cached.search("q", objective="o")
    assert exa.calls == 1
    assert a.output.content == b.output.content == {"series": [{"gse": "GSE1", "url": "u"}]}
    assert b.results[0].highlights == ["GSE1 here"] and b.cost_dollars.total == 0.01
    await cached.search("q", objective="other")
    assert exa.calls == 2

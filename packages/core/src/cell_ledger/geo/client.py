"""Client over NCBI E-utilities for GEO series search (``db=gds``).

Every query is AND-ed with :data:`ELIGIBILITY`, so only human, bulk RNA-seq series
that already have NCBI-generated raw counts can come back. Callers pass several
queries (synonyms, abbreviations, cell-line names); results are unioned and each
hit records which queries matched it.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field, computed_field

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

ELIGIBILITY = (
    '"Homo sapiens"[Organism]'
    ' AND "expression profiling by high throughput sequencing"[DataSet Type]'
    " AND gse[ETYP]"
    ' AND "rnaseq counts"[Filter]'
)

SUMMARY_BATCH = 200
MAX_ATTEMPTS = 3
RETRY_STATUS = {429, 500, 502, 503, 504}


class GeoSeriesHit(BaseModel):
    gse: str = Field(pattern=r"^GSE\d+$")
    title: str
    summary: str
    taxa: list[str]
    series_types: list[str]
    n_samples: int
    published: date | None
    pubmed_ids: list[str]
    matched_queries: list[str] = Field(description="Which submitted queries found this series")

    @computed_field
    @property
    def mixed_organism(self) -> bool:
        """True when the series also has non-human samples; they are excluded at fetch time."""
        return any(t != "Homo sapiens" for t in self.taxa)


class QueryStats(BaseModel):
    query: str
    term: str = Field(description="Exact term sent to esearch, for provenance")
    total: int = Field(description="Series in GEO matching the term")
    returned: int


class SearchResult(BaseModel):
    queries: list[QueryStats]
    hits: list[GeoSeriesHit]


class RateLimiter:
    """Spaces calls at least ``1/rate`` seconds apart across all callers."""

    def __init__(self, rate: float) -> None:
        self._interval = 1.0 / rate
        self._next = 0.0
        self._lock = asyncio.Lock()

    async def wait(self) -> None:
        async with self._lock:
            now = time.monotonic()
            if self._next > now:
                await asyncio.sleep(self._next - now)
            self._next = max(now, self._next) + self._interval


class GeoClient:
    """Rate-limited E-utilities client: 3 requests/s, or 10 with an NCBI API key.

    Share one instance per process so the limit holds across concurrent requests.
    """

    def __init__(
        self,
        http: httpx.AsyncClient,
        *,
        api_key: str | None = None,
        tool: str = "cell-ledger",
        retry_delay: float = 1.0,
    ) -> None:
        self._http = http
        self._api_key = api_key
        self._tool = tool
        self._retry_delay = retry_delay
        self._limiter = RateLimiter(10 if api_key else 3)

    async def _call(self, endpoint: str, params: dict[str, str], *, post: bool = False) -> Any:
        params = {**params, "retmode": "json", "tool": self._tool}
        if self._api_key:
            params["api_key"] = self._api_key
        url = f"{EUTILS}/{endpoint}"
        for attempt in range(1, MAX_ATTEMPTS + 1):
            await self._limiter.wait()
            if post:
                r = await self._http.post(url, data=params)
            else:
                r = await self._http.get(url, params=params)
            if r.status_code in RETRY_STATUS and attempt < MAX_ATTEMPTS:
                await asyncio.sleep(self._retry_delay * 2 ** (attempt - 1))
                continue
            r.raise_for_status()
            return r.json()
        raise AssertionError("unreachable")

    async def search_series(
        self,
        queries: Sequence[str],
        *,
        limit_per_query: int = 100,
        since: int | None = None,
    ) -> SearchResult:
        """Run each query with the eligibility filter and union the hits.

        Hits keep first-seen order: query order, then GEO's relevance order.
        """
        cleaned = list(dict.fromkeys(q.strip() for q in queries if q.strip()))
        if not cleaned:
            raise ValueError("at least one non-empty query is required")

        stats: list[QueryStats] = []
        matched: dict[str, list[str]] = {}  # gds uid -> queries, insertion-ordered
        for query in cleaned:
            term = f"({query}) AND {ELIGIBILITY}"
            if since is not None:
                term += f' AND ("{since}/01/01"[PDAT] : "3000"[PDAT])'
            body = await self._call(
                "esearch.fcgi", {"db": "gds", "term": term, "retmax": str(limit_per_query)}
            )
            res = body["esearchresult"]
            ids: list[str] = res["idlist"]
            stats.append(
                QueryStats(query=query, term=term, total=int(res["count"]), returned=len(ids))
            )
            for uid in ids:
                matched.setdefault(uid, []).append(query)

        hits: list[GeoSeriesHit] = []
        uids = list(matched)
        for i in range(0, len(uids), SUMMARY_BATCH):
            batch = uids[i : i + SUMMARY_BATCH]
            body = await self._call(
                "esummary.fcgi", {"db": "gds", "id": ",".join(batch)}, post=True
            )
            result = body["result"]
            hits.extend(_to_hit(result[uid], matched[uid]) for uid in batch if uid in result)
        return SearchResult(queries=stats, hits=hits)


def _split(value: str) -> list[str]:
    return [p.strip() for p in value.split(";") if p.strip()]


def _parse_pdat(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%Y/%m/%d").date()
    except (TypeError, ValueError):
        return None


def _to_hit(doc: dict[str, Any], matched_queries: list[str]) -> GeoSeriesHit:
    return GeoSeriesHit(
        gse=doc["accession"],
        title=doc["title"],
        summary=doc["summary"],
        taxa=_split(doc.get("taxon", "")),
        series_types=_split(doc.get("gdstype", "")),
        n_samples=int(doc.get("n_samples", 0)),
        published=_parse_pdat(doc.get("pdat", "")),
        pubmed_ids=[str(p) for p in doc.get("pubmedids", [])],
        matched_queries=matched_queries,
    )

"""Client over NCBI E-utilities for GEO series search (``db=gds``).

Every query is AND-ed with :data:`ELIGIBILITY`, so only human, bulk RNA-seq series
that already have NCBI-generated raw counts can come back. Callers pass several
queries (synonyms, abbreviations, cell-line names); results are unioned and each
hit records which queries matched it.
"""

from __future__ import annotations

import asyncio
import gzip
import re
import time
import zlib
from collections.abc import Sequence
from datetime import date, datetime
from typing import Any

import httpx
from pydantic import BaseModel, Field, computed_field

from cell_ledger.geo.fetch import FTP, counts_name, counts_url, series_stem, soft_url
from cell_ledger.geo.soft import GeoSeries, parse_soft

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"

ELIGIBILITY = (
    '"Homo sapiens"[Organism]'
    ' AND "expression profiling by high throughput sequencing"[DataSet Type]'
    " AND gse[ETYP]"
    ' AND "rnaseq counts"[Filter]'
)

SUMMARY_BATCH = 200
FILE_CONCURRENCY = 8
"""Downloads from NCBI's file server at once, across all callers of one client."""
HEADER_LIMIT = 2_000_000
"""Decompressed bytes read from a count table before giving up on finding its header line."""
VERIFY_BATCH = 100
_GSE = re.compile(r"GSE\d+")
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


class VerifyResult(BaseModel):
    hits: list[GeoSeriesHit] = Field(description="Accessions that exist and pass the filter")
    ineligible: list[str] = Field(description="Accessions that do not exist or fail the filter")


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
        self._files = asyncio.Semaphore(FILE_CONCURRENCY)

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

        return SearchResult(queries=stats, hits=await self._summaries(matched))

    async def verify_series(self, gses: Sequence[str]) -> VerifyResult:
        """Check accessions against :data:`ELIGIBILITY` in one search per batch.

        Use this on accessions from any outside source (web search, an LLM, a paper):
        only those that exist and pass the filter come back as hits.
        """
        wanted = list(dict.fromkeys(g.strip().upper() for g in gses))
        bad = [g for g in wanted if not _GSE.fullmatch(g)]
        if bad:
            raise ValueError(f"not GEO series accessions: {bad}")
        matched: dict[str, list[str]] = {}
        for i in range(0, len(wanted), VERIFY_BATCH):
            batch = wanted[i : i + VERIFY_BATCH]
            ors = " OR ".join(f"{g}[ACCN]" for g in batch)
            body = await self._call(
                "esearch.fcgi",
                {"db": "gds", "term": f"({ors}) AND {ELIGIBILITY}", "retmax": str(len(batch))},
                post=True,
            )
            for uid in body["esearchresult"]["idlist"]:
                matched[uid] = []
        hits = await self._summaries(matched)
        eligible = {h.gse for h in hits}
        return VerifyResult(hits=hits, ineligible=[g for g in wanted if g not in eligible])

    async def exists_series(self, gses: Sequence[str]) -> list[str]:
        """Which of the accessions exist in GEO as series at all, eligible or not.

        The evals use this on a baseline's output to split accessions that do not exist
        (fabricated) from ones that exist but are not human bulk RNA-seq with counts.
        """
        wanted = list(dict.fromkeys(g.strip().upper() for g in gses))
        bad = [g for g in wanted if not _GSE.fullmatch(g)]
        if bad:
            raise ValueError(f"not GEO series accessions: {bad}")
        matched: dict[str, list[str]] = {}
        for i in range(0, len(wanted), VERIFY_BATCH):
            batch = wanted[i : i + VERIFY_BATCH]
            ors = " OR ".join(f"{g}[ACCN]" for g in batch)
            body = await self._call(
                "esearch.fcgi",
                {"db": "gds", "term": f"({ors}) AND gse[ETYP]", "retmax": str(len(batch))},
                post=True,
            )
            for uid in body["esearchresult"]["idlist"]:
                matched[uid] = []
        found = {h.gse for h in await self._summaries(matched)}
        return [g for g in wanted if g in found]

    async def series_record(self, gse: str) -> GeoSeries:
        """A series' family SOFT file, parsed: series text and every sample's fields, as GEO
        has them. One small download (a few KB compressed) from NCBI's file server."""
        if not _GSE.fullmatch(gse):
            raise ValueError(f"not a GEO series accession: {gse!r}")
        async with self._files:
            r = await self._http.get(soft_url(gse))
        r.raise_for_status()
        return parse_soft(gzip.decompress(r.content).decode("utf-8", errors="replace"))

    async def count_columns(self, gse: str) -> list[str] | None:
        """The GSM columns of the series' NCBI raw-count table, read from its header line
        only: the stream is closed as soon as that line is decompressed. None when NCBI has
        no count table for the series."""
        if not _GSE.fullmatch(gse):
            raise ValueError(f"not a GEO series accession: {gse!r}")
        async with self._files:
            name = counts_name(gse)
            header = await self._header(counts_url(gse, name))
            if header is None:  # the reference build in the file name may have changed
                listing = await self._http.get(f"{FTP}/rnaseq_counts/{series_stem(gse)}/")
                found = re.findall(rf'href="({gse}_raw_counts_[^"/]+\.tsv\.gz)"', listing.text)
                if listing.status_code == 200 and found and found[0] != name:
                    header = await self._header(counts_url(gse, found[0]))
        if header is None:
            return None
        return [c for c in header.split("\t")[1:] if c]

    async def _header(self, url: str) -> str | None:
        async with self._http.stream("GET", url) as r:
            if r.status_code == 404:
                return None
            r.raise_for_status()
            inflate = zlib.decompressobj(16 + zlib.MAX_WBITS)
            buf = b""
            async for chunk in r.aiter_bytes():
                buf += inflate.decompress(chunk)
                if b"\n" in buf or len(buf) > HEADER_LIMIT:
                    break
        return buf.split(b"\n", 1)[0].decode("utf-8", errors="replace").rstrip("\r")

    async def _summaries(self, matched: dict[str, list[str]]) -> list[GeoSeriesHit]:
        """esummary for gds uids, batched; keeps the order of ``matched``."""
        hits: list[GeoSeriesHit] = []
        uids = list(matched)
        for i in range(0, len(uids), SUMMARY_BATCH):
            batch = uids[i : i + SUMMARY_BATCH]
            body = await self._call(
                "esummary.fcgi", {"db": "gds", "id": ",".join(batch)}, post=True
            )
            result = body["result"]
            hits.extend(_to_hit(result[uid], matched[uid]) for uid in batch if uid in result)
        return hits


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

"""Find GEO series through Exa web search, then keep only what GEO itself confirms.

Exa reaches pages GEO's keyword search misses (papers' data-availability
statements, differently worded series pages). It only nominates accessions:
every one is re-checked with :meth:`GeoClient.verify_series`, so an invented,
non-human, microarray or count-less series never reaches the user.
"""

from __future__ import annotations

import re
from typing import Any, Protocol

from pydantic import BaseModel, Field

from cell_ledger.geo import GeoClient, GeoSeriesHit

GSE = re.compile(r"\bGSE\d{2,}\b")

# Exa's recommended wording for the objective parameter; keep it verbatim.
OBJECTIVE_DESCRIPTION = (
    "Goal for this search turn; say which documents should rank first, which should be "
    "excluded, and what specific facts or figures to pull from them."
)

# Tool definition for Claude. Results are GEO-verified series, not raw web pages.
FIND_SERIES_TOOL: dict[str, Any] = {
    "name": "find_geo_series_on_web",
    "description": (
        "Search the live web (NCBI GEO pages and papers' data availability statements) for "
        "GEO series that match the user's request. Use it alongside the GEO keyword search to "
        "catch series described in different words. Returns only series confirmed by GEO as "
        "human bulk RNA-seq with NCBI raw counts, plus the accessions that were rejected."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "objective": {"type": "string", "description": OBJECTIVE_DESCRIPTION},
        },
        "required": ["query", "objective"],
    },
}

SYSTEM_PROMPT = (
    "Report NCBI GEO series accessions (GSE followed by digits) printed on the retrieved pages, "
    "with the URL of the page each appears on. Prefer GEO series pages and the data "
    "availability sections of papers. Omit any accession that is not printed on a page; never "
    "guess, complete or construct one."
)

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "series": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"gse": {"type": "string"}, "url": {"type": "string"}},
                "required": ["gse", "url"],
            },
        }
    },
    "required": ["series"],
}


class ExaSearcher(Protocol):
    """The slice of ``exa_py.AsyncExa`` used here (lets tests pass a fake)."""

    async def search(self, query: str, **kwargs: Any) -> Any: ...


class WebSeriesHit(BaseModel):
    hit: GeoSeriesHit
    found_at: list[str] = Field(description="Pages where Exa found the accession")


class WebSearchResult(BaseModel):
    query: str
    objective: str
    nominated: list[str] = Field(description="Accessions Exa returned, before GEO checks")
    verified: list[WebSeriesHit]
    rejected: list[str] = Field(description="Nominated but missing from GEO or ineligible")
    exa_cost_dollars: float | None = None


def _nominations(response: Any) -> dict[str, list[str]]:
    """Accession -> page URLs, from structured output and from page text/URLs."""
    found: dict[str, list[str]] = {}

    def add(gse: str, url: str) -> None:
        urls = found.setdefault(gse.upper(), [])
        if url and url not in urls:
            urls.append(url)

    output = getattr(response, "output", None)
    content = getattr(output, "content", None)
    if isinstance(content, dict):
        for item in content.get("series") or []:
            if isinstance(item, dict):
                for gse in GSE.findall(str(item.get("gse", ""))):
                    add(gse, str(item.get("url", "")))

    for r in getattr(response, "results", None) or []:
        text = " ".join([r.url or "", r.title or "", *(getattr(r, "highlights", None) or [])])
        for gse in GSE.findall(text):
            add(gse, r.url or "")
    return found


async def find_series_on_web(
    exa: ExaSearcher, geo: GeoClient, query: str, objective: str
) -> WebSearchResult:
    response = await exa.search(
        query,
        type="auto",
        objective=objective,
        contents={"highlights": True},
        system_prompt=SYSTEM_PROMPT,
        output_schema=OUTPUT_SCHEMA,
    )
    nominated = _nominations(response)
    verified: list[WebSeriesHit] = []
    rejected: list[str] = []
    if nominated:
        check = await geo.verify_series(list(nominated))
        verified = [WebSeriesHit(hit=h, found_at=nominated[h.gse]) for h in check.hits]
        rejected = check.ineligible
    cost = getattr(getattr(response, "cost_dollars", None), "total", None)
    return WebSearchResult(
        query=query,
        objective=objective,
        nominated=list(nominated),
        verified=verified,
        rejected=rejected,
        exa_cost_dollars=float(cost) if isinstance(cost, int | float) else None,
    )

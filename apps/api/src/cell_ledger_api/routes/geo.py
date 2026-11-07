from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from cell_ledger.geo import GeoClient, SearchResult, VerifyResult
from cell_ledger_api.discovery import WebSearchResult, find_series_on_web

router = APIRouter(prefix="/geo", tags=["geo"])


class WebSearchRequest(BaseModel):
    query: Annotated[str, Field(min_length=1, max_length=500)]
    objective: Annotated[str, Field(min_length=1, max_length=4096)]


class VerifyRequest(BaseModel):
    gses: Annotated[
        list[Annotated[str, Field(pattern=r"^[Gg][Ss][Ee]\d+$")]],
        Field(min_length=1, max_length=500),
    ]


@router.post("/web-search", operation_id="searchGeoOnWeb")
async def search_geo_on_web(body: WebSearchRequest, request: Request) -> WebSearchResult:
    """Exa web search for GEO series; only GEO-verified, eligible series come back."""
    exa = request.app.state.exa
    if exa is None:
        raise HTTPException(503, "Exa is not configured (CELL_LEDGER_EXA_API_KEY)")
    return await find_series_on_web(exa, request.app.state.geo, body.query, body.objective)


@router.post("/verify", operation_id="verifyGeoSeries")
async def verify_geo_series(body: VerifyRequest, request: Request) -> VerifyResult:
    """Which of these accessions exist and pass the eligibility filter."""
    geo: GeoClient = request.app.state.geo
    return await geo.verify_series(body.gses)


class SearchRequest(BaseModel):
    queries: Annotated[list[str], Field(min_length=1, max_length=10)]
    limit_per_query: int = Field(default=50, ge=1, le=500)
    since: int | None = Field(default=None, ge=2000, le=2100, description="Published in or after")


@router.post("/search", operation_id="searchGeo")
async def search_geo(body: SearchRequest, request: Request) -> SearchResult:
    """Search GEO for human bulk RNA-seq series that have NCBI raw counts."""
    geo: GeoClient = request.app.state.geo
    try:
        return await geo.search_series(
            body.queries, limit_per_query=body.limit_per_query, since=body.since
        )
    except ValueError as e:
        raise HTTPException(422, str(e)) from e

from typing import Annotated

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from cell_ledger.geo import GeoClient, SearchResult

router = APIRouter(prefix="/geo", tags=["geo"])


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

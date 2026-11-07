"""Thin client over NCBI E-utilities for the GEO DataSets (``gds``) database."""

from __future__ import annotations

import httpx
from pydantic import BaseModel

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


class GeoSeriesHit(BaseModel):
    gse: str
    title: str
    summary: str
    organism: str
    n_samples: int


async def search_series(
    query: str, *, limit: int = 20, client: httpx.AsyncClient | None = None
) -> list[GeoSeriesHit]:
    """Search GEO series matching ``query`` and return basic metadata.

    Restricts to series (GSE) entries and uses esummary for the hit details.
    """
    own_client = client is None
    client = client or httpx.AsyncClient(timeout=30)
    try:
        term = f"({query}) AND gse[ETYP]"
        r = await client.get(
            f"{EUTILS}/esearch.fcgi",
            params={"db": "gds", "term": term, "retmax": limit, "retmode": "json"},
        )
        r.raise_for_status()
        ids: list[str] = r.json()["esearchresult"]["idlist"]
        if not ids:
            return []
        r = await client.get(
            f"{EUTILS}/esummary.fcgi",
            params={"db": "gds", "id": ",".join(ids), "retmode": "json"},
        )
        r.raise_for_status()
        result = r.json()["result"]
        hits = []
        for uid in ids:
            doc = result[uid]
            hits.append(
                GeoSeriesHit(
                    gse=f"GSE{doc['gse']}",
                    title=doc["title"],
                    summary=doc["summary"],
                    organism=doc.get("taxon", ""),
                    n_samples=int(doc.get("n_samples", 0)),
                )
            )
        return hits
    finally:
        if own_client:
            await client.aclose()

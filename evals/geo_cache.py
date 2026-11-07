"""GEO and Exa responses cached on disk for the length of an eval run.

GEO search results drift and Exa is live, so two repeats of the same case minutes apart can
see different pools. Within one run every identical request gets the identical answer; a new
run gets a fresh cache unless it is pointed at an old one (which is how to A/B two prompts
against the exact same GEO).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
from pydantic import BaseModel

from cell_ledger.geo import GeoClient, SearchResult, VerifyResult


def _key(name: str, payload: Any) -> str:
    return hashlib.sha256(
        json.dumps([name, payload], sort_keys=True, default=str).encode()
    ).hexdigest()


class CachedGeoClient(GeoClient):
    """``GeoClient`` whose search, verify and exists calls are memoised in ``cache_dir``."""

    def __init__(
        self,
        http: httpx.AsyncClient,
        cache_dir: Path,
        *,
        api_key: str | None = None,
        **kw: Any,
    ) -> None:
        super().__init__(http, api_key=api_key, **kw)
        self.cache_dir = cache_dir
        self.hits = 0
        self.misses = 0
        cache_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str, payload: Any) -> Path:
        return self.cache_dir / f"{name}-{_key(name, payload)[:24]}.json"

    async def _cached(
        self, name: str, payload: Any, model: type[BaseModel] | None, compute: Any
    ) -> Any:
        path = self._path(name, payload)
        if path.exists():
            self.hits += 1
            text = path.read_text()
            return model.model_validate_json(text) if model else json.loads(text)
        self.misses += 1
        value = await compute()
        path.write_text(
            value.model_dump_json(indent=1) if isinstance(value, BaseModel) else json.dumps(value)
        )
        return value

    async def search_series(
        self, queries: Sequence[str], *, limit_per_query: int = 100, since: int | None = None
    ) -> SearchResult:
        payload = {"queries": list(queries), "limit": limit_per_query, "since": since}
        return await self._cached(
            "search",
            payload,
            SearchResult,
            lambda: super(CachedGeoClient, self).search_series(
                queries, limit_per_query=limit_per_query, since=since
            ),
        )

    async def verify_series(self, gses: Sequence[str]) -> VerifyResult:
        wanted = sorted({g.strip().upper() for g in gses})
        return await self._cached(
            "verify", wanted, VerifyResult, lambda: super(CachedGeoClient, self).verify_series(gses)
        )

    async def exists_series(self, gses: Sequence[str]) -> list[str]:
        wanted = sorted({g.strip().upper() for g in gses})
        return await self._cached(
            "exists", wanted, None, lambda: super(CachedGeoClient, self).exists_series(gses)
        )


class CachedExa:
    """Memoises ``exa.search`` to the fields ``find_series_on_web`` reads."""

    def __init__(self, exa: Any, cache_dir: Path) -> None:
        self._exa = exa
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    async def search(self, query: str, **kwargs: Any) -> Any:
        path = self.cache_dir / f"exa-{_key('exa', [query, kwargs])[:24]}.json"
        if path.exists():
            return _inflate(json.loads(path.read_text()))
        response = await self._exa.search(query, **kwargs)
        flat = _flatten(response)
        path.write_text(json.dumps(flat))
        return _inflate(flat)


def _flatten(response: Any) -> dict[str, Any]:
    output = getattr(response, "output", None)
    content = getattr(output, "content", None)
    cost = getattr(getattr(response, "cost_dollars", None), "total", None)
    return {
        "content": content if isinstance(content, dict) else None,
        "results": [
            {
                "url": getattr(r, "url", None),
                "title": getattr(r, "title", None),
                "highlights": list(getattr(r, "highlights", None) or []),
            }
            for r in getattr(response, "results", None) or []
        ],
        "cost": float(cost) if isinstance(cost, int | float) else None,
    }


def _inflate(flat: dict[str, Any]) -> Any:
    return SimpleNamespace(
        output=SimpleNamespace(content=flat["content"]) if flat["content"] is not None else None,
        results=[SimpleNamespace(**r) for r in flat["results"]],
        cost_dollars=SimpleNamespace(total=flat["cost"]) if flat["cost"] is not None else None,
    )

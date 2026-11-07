"""The discover step's tools: each one's definition for Claude next to the code that runs it.

A handler returns the text Claude reads and a one-line summary for the UI, and records on the
:class:`ToolCall` what GEO actually returned. Its ``confirmed`` accessions are the only ones
the final answer may name. A handler raises :class:`ToolError` for a failure Claude should see
and work around; :func:`execute` turns that, and any other exception, into an error result,
because a failed search is a tool error, not a dead agent.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field

from cell_ledger.geo import GeoClient, GeoSeriesHit
from cell_ledger_api.discovery import FIND_SERIES_TOOL, ExaSearcher, find_series_on_web

log = logging.getLogger(__name__)


class QueryTrace(BaseModel):
    query: str
    total: int = Field(description="eligible series in GEO matching this query")
    returned: int
    gses: list[str] = Field(description="accessions this query returned, in GEO's order")


class ToolCall(BaseModel):
    """One tool invocation as the code saw it: inputs, what GEO returned, what Claude was shown."""

    tool: str
    input: dict[str, Any] = Field(default_factory=dict)
    queries: list[QueryTrace] = Field(default_factory=list, description="search_geo only")
    confirmed: list[str] = Field(
        default_factory=list, description="accessions GEO confirmed eligible in this call"
    )
    shown: list[str] = Field(
        default_factory=list, description="the confirmed accessions whose records Claude saw"
    )
    ineligible: list[str] = Field(
        default_factory=list, description="nominated accessions GEO did not confirm"
    )
    error: str | None = None


class ToolError(Exception):
    def __init__(self, message: str, *, summary: str) -> None:
        super().__init__(message)
        self.message = message
        self.summary = summary


@dataclass(frozen=True)
class ToolResult:
    content: str
    """What Claude reads."""
    summary: str
    """One line for the UI."""
    is_error: bool = False


Handler = Callable[[dict[str, Any], ToolCall], Awaitable[ToolResult]]


@dataclass(frozen=True)
class Tool:
    definition: dict[str, Any]
    run: Handler

    @property
    def name(self) -> str:
        return self.definition["name"]


def _hit(h: GeoSeriesHit, **extra: Any) -> dict[str, Any]:
    """A series as Claude sees it in every tool result."""
    return {
        "gse": h.gse,
        "title": h.title,
        "n_samples": h.n_samples,
        "summary": h.summary[:400],
        **extra,
    }


def _json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False)


def search_geo(geo: GeoClient) -> Tool:
    async def run(args: dict[str, Any], call: ToolCall) -> ToolResult:
        queries = [q for q in args.get("queries", []) if isinstance(q, str) and q.strip()]
        if not queries:
            raise ToolError("no queries given", summary="search_geo: no queries")
        since = args.get("since")
        res = await geo.search_series(
            queries[:10], limit_per_query=25, since=since if isinstance(since, int) else None
        )
        shown = res.hits[:40]
        call.queries = [
            QueryTrace(
                query=q.query,
                total=q.total,
                returned=q.returned,
                gses=[h.gse for h in res.hits if q.query in h.matched_queries],
            )
            for q in res.queries
        ]
        call.confirmed = [h.gse for h in res.hits]
        call.shown = [h.gse for h in shown]
        hits = [
            _hit(
                h,
                published=h.published.isoformat() if h.published else None,
                matched_queries=h.matched_queries,
            )
            for h in shown
        ]
        stats = [{"query": q.query, "total": q.total, "returned": q.returned} for q in res.queries]
        return ToolResult(
            _json({"queries": stats, "hits": hits}),
            f"searched GEO: {len(queries)} queries, {len(res.hits)} series",
        )

    return Tool(
        {
            "name": "search_geo",
            "description": (
                "Keyword search of NCBI GEO for human bulk RNA-seq series with NCBI raw "
                "counts. Pass several differently worded queries at once; results are "
                "merged and say which queries found each series."
            ),
            "strict": True,
            "eager_input_streaming": True,
            "input_schema": {
                "type": "object",
                "properties": {
                    "queries": {"type": "array", "items": {"type": "string"}},
                    "since": {
                        "type": ["integer", "null"],
                        "description": "only series published in or after this year",
                    },
                },
                "required": ["queries", "since"],
                "additionalProperties": False,
            },
        },
        run,
    )


def verify_geo_series(geo: GeoClient) -> Tool:
    async def run(args: dict[str, Any], call: ToolCall) -> ToolResult:
        gses = [g for g in args.get("gses", []) if isinstance(g, str)]
        try:
            res = await geo.verify_series(gses)
        except ValueError as e:
            raise ToolError(str(e), summary="verify: invalid accession") from e
        call.confirmed = call.shown = [h.gse for h in res.hits]
        call.ineligible = list(res.ineligible)
        return ToolResult(
            _json({"hits": [_hit(h) for h in res.hits], "ineligible": res.ineligible}),
            f"verified {len(gses)}: {len(res.hits)} eligible",
        )

    return Tool(
        {
            "name": "verify_geo_series",
            "description": (
                "Check accessions you got from anywhere else (a paper, memory, the web) "
                "against GEO. Only accessions that exist and are human bulk RNA-seq with "
                "raw counts come back as hits."
            ),
            "strict": True,
            "input_schema": {
                "type": "object",
                "properties": {"gses": {"type": "array", "items": {"type": "string"}}},
                "required": ["gses"],
                "additionalProperties": False,
            },
        },
        run,
    )


def find_geo_series_on_web(exa: ExaSearcher, geo: GeoClient) -> Tool:
    async def run(args: dict[str, Any], call: ToolCall) -> ToolResult:
        res = await find_series_on_web(
            exa, geo, str(args.get("query", "")), str(args.get("objective", ""))
        )
        call.confirmed = call.shown = [v.hit.gse for v in res.verified]
        call.ineligible = list(res.rejected)
        payload = {
            "verified": [_hit(v.hit, found_at=v.found_at[:3]) for v in res.verified],
            "rejected": res.rejected,
        }
        return ToolResult(
            _json(payload),
            f"web search: {len(res.verified)} verified, {len(res.rejected)} rejected",
        )

    return Tool({**FIND_SERIES_TOOL, "strict": True}, run)


def geo_tools(geo: GeoClient, exa: ExaSearcher | None) -> dict[str, Tool]:
    """The tools Claude gets in the discover step, by name, in the order it is shown them."""
    tools = [search_geo(geo), verify_geo_series(geo)]
    if exa is not None:
        tools.append(find_geo_series_on_web(exa, geo))
    return {t.name: t for t in tools}


async def execute(
    tools: Mapping[str, Tool], name: str, args: dict[str, Any]
) -> tuple[ToolCall, ToolResult]:
    """Run one tool call; never raises. The :class:`ToolCall` goes into the trace."""
    call = ToolCall(tool=name, input=args)
    tool = tools.get(name)
    try:
        if tool is None:
            raise ToolError(f"unknown tool {name}", summary=f"unknown tool {name}")
        return call, await tool.run(args, call)
    except ToolError as e:
        call.error = e.message
        return call, ToolResult(f"error: {e.message}", e.summary, is_error=True)
    except Exception as e:
        log.warning("tool %s failed: %s", name, e)
        call.error = f"{type(e).__name__}: {e}"
        return call, ToolResult(f"error: {call.error}", f"{name} failed", is_error=True)

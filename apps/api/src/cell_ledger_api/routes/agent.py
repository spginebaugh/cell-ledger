"""Streaming endpoints for the discover and design steps (see ``cell_ledger_api.agent``)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import Any, Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from cell_ledger.geo import DatasetRecord
from cell_ledger_api.agent import (
    Agent,
    AgentUnavailable,
    DatasetNotReady,
    DesignProposal,
    DesignRequest,
    DiscoverRequest,
    DiscoveryResult,
    sse,
)
from cell_ledger_api.routes.sessions import Gse, SessionId
from cell_ledger_api.sessions import SessionService

log = logging.getLogger(__name__)
router = APIRouter(prefix="/sessions/{session_id}", tags=["agent"])
types_router = APIRouter(prefix="/agent", tags=["agent"])


class AgentEvent(BaseModel):
    """One Server-Sent Event from ``discoverDatasets`` or ``designContrast``."""

    type: Literal["thinking", "tool", "result", "error", "done"]
    delta: str | None = Field(default=None, description="thinking: text to append")
    name: str | None = Field(default=None, description="tool: which tool ran")
    input: dict[str, Any] | None = Field(default=None, description="tool: its arguments")
    summary: str | None = Field(default=None, description="tool: one line for the UI")
    data: dict[str, Any] | None = Field(default=None, description="result: the payload")
    message: str | None = Field(default=None, description="error: what went wrong")


class AgentTypes(BaseModel):
    """Never returned with content; exists so the streamed payloads appear in the OpenAPI
    schema and the generated client has types for them."""

    event: AgentEvent
    discovery: DiscoveryResult | None = None
    design: DesignProposal | None = None
    available: bool


@types_router.get("/types", operation_id="getAgentTypes")
async def get_agent_types(request: Request) -> AgentTypes:
    """Whether Claude is configured, plus the schemas of the streamed payloads."""
    a: Agent = request.app.state.agent
    return AgentTypes(event=AgentEvent(type="done"), available=a.available)


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def agent(request: Request) -> Agent:
    a: Agent = request.app.state.agent
    if not a.available:
        raise HTTPException(503, "Claude is not configured (CELL_LEDGER_ANTHROPIC_API_KEY)")
    return a


def sessions(request: Request) -> SessionService:
    return request.app.state.sessions


async def _stream(work) -> AsyncIterator[dict[str, Any]]:  # type: ignore[no-untyped-def]
    """Run ``work(emit)`` while yielding the events it emits, then its result."""
    queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()

    async def emit(event: dict[str, Any]) -> None:
        await queue.put(event)

    async def runner() -> None:
        try:
            result = await work(emit)
            await queue.put({"type": "result", "data": result.model_dump(mode="json")})
        except (AgentUnavailable, DatasetNotReady) as e:
            await queue.put({"type": "error", "message": str(e)})
        except Exception as e:  # anthropic errors, network: tell the browser, log the rest
            log.exception("agent step failed")
            await queue.put({"type": "error", "message": f"{type(e).__name__}: {e}"})
        finally:
            await queue.put(None)

    task = asyncio.create_task(runner())
    try:
        while True:
            event = await queue.get()
            if event is None:
                break
            yield event
        yield {"type": "done"}
    finally:
        if not task.done():
            task.cancel()


@router.post("/discover", operation_id="discoverDatasets")
async def discover(
    session_id: SessionId, body: DiscoverRequest, request: Request
) -> StreamingResponse:
    """Stream Claude's search for datasets that answer the question (Server-Sent Events).

    Events: ``thinking`` (delta), ``tool`` (name, input, summary), ``result`` (a
    ``DiscoveryResult``), ``error`` (message), ``done``. The question is recorded on the
    session.
    """
    a = agent(request)
    svc = sessions(request)
    await svc.update(session_id, question=body.question, state=None)

    async def work(emit):  # type: ignore[no-untyped-def]
        return await a.discover(body.question, emit)

    return StreamingResponse(
        sse(_stream(work)), media_type="text/event-stream", headers=SSE_HEADERS
    )


@router.post("/datasets/{gse}/design", operation_id="designContrast")
async def design(
    session_id: SessionId, gse: Gse, body: DesignRequest, request: Request
) -> StreamingResponse:
    """Stream Claude's sample labelling and contrast proposal for one collected dataset.

    Events as for ``discoverDatasets``; the ``result`` is a ``DesignProposal`` whose design
    carries ``status: proposed`` contrasts. Confirm them (set ``status: confirmed``) and
    submit the design to ``startRun``.
    """
    a = agent(request)
    svc = sessions(request)
    row = await svc.db.get_dataset(session_id, gse)
    if row is None:
        await svc.get(session_id)
        raise HTTPException(404, f"{gse} is not in this session")
    if row["status"] != "ready" or not row["record"]:
        raise HTTPException(409, f"{gse} is {row['status']}; collect it first")
    record = DatasetRecord.model_validate(row["record"])

    async def work(emit):  # type: ignore[no-untyped-def]
        return await a.design(record, body, emit)

    return StreamingResponse(
        sse(_stream(work)), media_type="text/event-stream", headers=SSE_HEADERS
    )

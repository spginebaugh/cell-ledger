"""Progress events from a running pipeline, for a parent process to tail.

Deliberately free of analysis imports so the API can import it without loading scanpy.
A sink is any callable taking one dict. The CLI installs one that prints a JSON line per
event to stdout (``cell-ledger run --progress``); the API reads those lines from the
subprocess to show a live stepper. Events::

    {"event": "run",  "status": "started",  "gse": "GSE1", "contrast": "a_vs_b", "at": "<iso>"}
    {"event": "step", "name": "deseq2", "status": "started",  ..., "at": "<iso>"}
    {"event": "step", "name": "deseq2", "status": "finished", ..., "seconds": 41.2}
    {"event": "run",  "status": "finished", "result": "complete", ...}
"""

from __future__ import annotations

import contextlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

PROGRESS_PREFIX = "CL_PROGRESS "

ProgressSink = Callable[[dict[str, Any]], None]
_sink: ProgressSink | None = None
_context: dict[str, Any] = {}


def set_progress_sink(sink: ProgressSink | None, **context: Any) -> None:
    """Install (or clear) the process-wide sink; ``context`` rides on every event."""
    global _sink, _context
    _sink = sink
    _context = dict(context)


def emit(event: str, **fields: Any) -> None:
    if _sink is None:
        return
    with contextlib.suppress(Exception):  # a broken sink must never break the analysis
        _sink({"event": event, "at": datetime.now(UTC).isoformat(), **_context, **fields})


def print_progress(event: dict[str, Any]) -> None:
    """The stdout sink: one ``CL_PROGRESS {json}`` line per event."""
    print(PROGRESS_PREFIX + json.dumps(event, separators=(",", ":")), flush=True)


def parse_progress_line(line: bytes | str) -> dict[str, Any] | None:
    """The event in a stdout line, or None when the line is ordinary output."""
    text = line.decode("utf-8", "replace") if isinstance(line, bytes) else line
    if not text.startswith(PROGRESS_PREFIX):
        return None
    try:
        event = json.loads(text[len(PROGRESS_PREFIX) :])
    except ValueError:
        return None
    return event if isinstance(event, dict) else None

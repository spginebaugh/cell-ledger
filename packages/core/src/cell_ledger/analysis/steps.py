"""Timing and warning capture for pipeline steps; each step also emits a progress event
(see :mod:`cell_ledger.progress`)."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from cell_ledger.progress import emit, set_progress_sink
from cell_ledger.report.models import StepRecord

NOISE: tuple[type[Warning], ...] = (DeprecationWarning, PendingDeprecationWarning, FutureWarning)

__all__ = ["emit", "set_progress_sink", "step"]


@contextmanager
def step(records: list[StepRecord], name: str, **params: Any) -> Iterator[StepRecord]:
    """Run a step, append a StepRecord with duration and any Python warnings it raised."""
    rec = StepRecord(name=name, params=params, started_at=datetime.now(UTC))
    emit("step", name=name, status="started")
    start = perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield rec
        finally:
            rec.seconds = round(perf_counter() - start, 3)
            emit("step", name=name, status="finished", seconds=rec.seconds)
            seen: list[str] = []
            for w in caught:
                if issubclass(w.category, NOISE):
                    continue  # library deprecation chatter, not about this dataset
                msg = str(w.message)
                if msg not in seen:
                    seen.append(msg)
            rec.warnings.extend(seen)
            records.append(rec)

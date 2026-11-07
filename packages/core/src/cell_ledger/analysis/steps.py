"""Timing and warning capture for pipeline steps."""

from __future__ import annotations

import warnings
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any

from cell_ledger.report.models import StepRecord

NOISE: tuple[type[Warning], ...] = (DeprecationWarning, PendingDeprecationWarning, FutureWarning)


@contextmanager
def step(records: list[StepRecord], name: str, **params: Any) -> Iterator[StepRecord]:
    """Run a step, append a StepRecord with duration and any Python warnings it raised."""
    rec = StepRecord(name=name, params=params, started_at=datetime.now(UTC))
    start = perf_counter()
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            yield rec
        finally:
            rec.seconds = round(perf_counter() - start, 3)
            seen: list[str] = []
            for w in caught:
                if issubclass(w.category, NOISE):
                    continue  # library deprecation chatter, not about this dataset
                msg = str(w.message)
                if msg not in seen:
                    seen.append(msg)
            rec.warnings.extend(seen)
            records.append(rec)

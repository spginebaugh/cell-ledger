"""Run a producer script against a cell-ledger checkout, so the readers read real outputs.

By default the checkout is this repository: the readers check what this tree's pipeline
writes. Set ``CELL_LEDGER_SHARED_CHECKOUT`` to another checkout (typically an unchanged
``main`` worktree) to check instead that the readers here still read what that code writes.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]


def producer_checkout() -> Path:
    configured = os.environ.get("CELL_LEDGER_SHARED_CHECKOUT")
    return Path(configured).resolve() if configured else REPO_ROOT


def run_producer(script: str, out: Path, *, timeout: float) -> None:
    """Run ``script`` with the checkout's ``cell_ledger`` first on the path; it receives the
    checkout and ``out`` as ``sys.argv[1:]``."""
    checkout = producer_checkout()
    proc = subprocess.run(
        [sys.executable, "-c", script, str(checkout), str(out)],
        cwd=checkout,
        env={
            **os.environ,
            "PYTHONPATH": str(checkout / "packages/core/src"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "MPLCONFIGDIR": str(out / "mpl"),
        },
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    assert proc.returncode == 0, f"producer at {checkout} failed:\n{proc.stdout}{proc.stderr}"

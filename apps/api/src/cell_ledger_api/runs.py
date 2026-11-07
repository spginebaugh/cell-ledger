"""Pipeline runs inside a session: ``cell-ledger run`` as a subprocess, state on disk.

Layout under ``<session>/runs/<GSE>/``::

    design.json              what was submitted (samplesheet + contrasts + markers)
    running.json             present while the subprocess is alive (RunMarker)
    run.log                  subprocess stdout + stderr
    <contrast>/report.json   written by the pipeline; status complete | qc_only | blocked
    <contrast>/failed.json   written here when the process ended without a report
    <contrast>/upload.json   mirror result for the contrast folder (UploadRecord)

The subprocess keeps scanpy and pydeseq2 out of the API process: memory is returned when
the run ends and a crash cannot take the server down. A semaphore caps concurrent runs
because each fit wants a few GB. Clients poll :meth:`RunService.statuses`.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import httpx
from pydantic import BaseModel, Field

from cell_ledger.report.models import AnalysisReport, MarkerExpectation
from cell_ledger.samplesheet import Contrast, SampleSheet
from cell_ledger_api.sessions import SessionService, upload_dir, write_json

log = logging.getLogger(__name__)

DEFAULT_COMMAND: tuple[str, ...] = (sys.executable, "-m", "cell_ledger.cli")


class RunRequest(BaseModel):
    """One design file, as ``cell-ledger run --design`` reads it, plus a few run options."""

    samplesheet: SampleSheet
    contrasts: list[Contrast] = Field(min_length=1)
    markers: list[MarkerExpectation] = Field(default_factory=list)
    genes: list[str] = Field(default_factory=list, description="symbols or GeneIDs to look up")
    enrichment: bool = True
    figures: bool = True


class RunMarker(BaseModel):
    started_at: datetime
    contrasts: list[str]


class UploadRecord(BaseModel):
    uploaded: bool = False
    error: str | None = None
    files: list[str] = Field(default_factory=list)
    finished_at: datetime


class RunFailure(BaseModel):
    error: str
    finished_at: datetime


RunState = Literal["running", "complete", "qc_only", "blocked", "failed"]


class RunStatus(BaseModel):
    gse: str
    contrast: str
    status: RunState
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error: str | None = Field(default=None, description="pipeline error or why the run failed")
    report: AnalysisReport | None = None
    uploaded: bool = False
    files: list[str] = Field(default_factory=list, description="names available for signed URLs")


class RunConflict(RuntimeError):
    pass


class CountsMissing(LookupError):
    pass


class RunService:
    def __init__(
        self,
        sessions: SessionService,
        *,
        max_concurrent: int = 2,
        n_cpus: int | None = None,
        timeout_minutes: float = 30,
        command: Sequence[str] = DEFAULT_COMMAND,
    ) -> None:
        self._sessions = sessions
        self._sem = asyncio.Semaphore(max_concurrent)
        self._n_cpus = n_cpus
        self._timeout = timeout_minutes * 60
        self._command = tuple(command)

    def runs_dir(self, session_id: str) -> Path:
        return self._sessions.dir(session_id) / "runs"

    # ------------------------------------------------------------- start

    async def start(self, session_id: str, req: RunRequest) -> list[RunStatus]:
        gse = req.samplesheet.gse
        counts = self._sessions.counts_path(session_id, gse)
        if counts is None:
            raise CountsMissing(f"{gse} has no collected counts in this session")
        if not self._sessions.annotation_path.exists():
            raise CountsMissing("shared annotation table not downloaded yet")
        out = self.runs_dir(session_id) / gse
        out.mkdir(parents=True, exist_ok=True)
        if (out / "running.json").exists():
            raise RunConflict(f"a run for {gse} is already in progress")
        names = [c.name for c in req.contrasts]
        for name in names:  # a rerun replaces the previous verdict for that contrast
            (out / name / "failed.json").unlink(missing_ok=True)
            (out / name / "upload.json").unlink(missing_ok=True)
        write_json(out / "design.json", req)
        marker = RunMarker(started_at=datetime.now(UTC), contrasts=names)
        write_json(out / "running.json", marker)
        self._sessions.spawn(self._run(session_id, gse, counts, req))
        return [
            RunStatus(gse=gse, contrast=n, status="running", started_at=marker.started_at)
            for n in names
        ]

    def _argv(self, gse: str, out: Path, counts: Path, req: RunRequest) -> list[str]:
        argv = [
            *self._command,
            "run",
            gse,
            "--design",
            str(out / "design.json"),
            "--counts",
            str(counts),
            "--annotation",
            str(self._sessions.annotation_path),
            "--out-root",
            str(out.parent),
        ]
        if req.genes:
            argv += ["--genes", ",".join(req.genes)]
        if not req.enrichment:
            argv.append("--no-enrichment")
        if not req.figures:
            argv.append("--no-figures")
        if self._n_cpus:
            argv += ["--n-cpus", str(self._n_cpus)]
        return argv

    async def _run(self, session_id: str, gse: str, counts: Path, req: RunRequest) -> None:
        out = self.runs_dir(session_id) / gse
        error: str | None = None
        async with self._sem:
            with (out / "run.log").open("ab") as logf:
                proc = await asyncio.create_subprocess_exec(
                    *self._argv(gse, out, counts, req),
                    stdout=logf,
                    stderr=asyncio.subprocess.STDOUT,
                )
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=self._timeout)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    error = f"killed after {self._timeout / 60:g} minutes"
                else:
                    if rc not in (0, 1):  # 1 = ran but not 'complete'; the report says why
                        error = f"pipeline exited with code {rc}; see run.log"
        now = datetime.now(UTC)
        for contrast in req.contrasts:
            cdir = out / contrast.name
            if not (cdir / "report.json").exists():
                cdir.mkdir(parents=True, exist_ok=True)
                write_json(
                    cdir / "failed.json",
                    RunFailure(
                        error=error or "pipeline wrote no report; see run.log", finished_at=now
                    ),
                )
            upload = UploadRecord(finished_at=now)
            if self._sessions.store is not None:
                try:
                    upload.files = await upload_dir(
                        self._sessions.store, f"{session_id}/runs/{gse}/{contrast.name}", cdir
                    )
                    upload.uploaded = True
                except httpx.HTTPError as e:
                    upload.error = f"{type(e).__name__}: {e}"
            write_json(cdir / "upload.json", upload)
        (out / "running.json").unlink(missing_ok=True)

    # ------------------------------------------------------------ status

    def statuses(self, session_id: str) -> list[RunStatus]:
        root = self.runs_dir(session_id)
        if not root.exists():
            return []
        out: list[RunStatus] = []
        for gdir in sorted(p for p in root.iterdir() if p.is_dir()):
            marker_path = gdir / "running.json"
            marker = (
                RunMarker.model_validate_json(marker_path.read_text())
                if marker_path.exists()
                else None
            )
            seen: set[str] = set()
            # The pipeline builds each result in a sibling ".<contrast>.tmp-<pid>" folder and
            # swaps it into place at the end; those are not contrasts.
            for cdir in sorted(p for p in gdir.iterdir() if p.is_dir() and p.name[0] != "."):
                seen.add(cdir.name)
                out.append(self._status(gdir.name, cdir, marker))
            if marker:  # contrasts whose folder the pipeline has not created yet
                out += [
                    RunStatus(
                        gse=gdir.name, contrast=n, status="running", started_at=marker.started_at
                    )
                    for n in marker.contrasts
                    if n not in seen
                ]
        return out

    def _status(self, gse: str, cdir: Path, marker: RunMarker | None) -> RunStatus:
        st = RunStatus(gse=gse, contrast=cdir.name, status="running")
        if marker and cdir.name in marker.contrasts:
            st.started_at = marker.started_at
            return st
        if (cdir / "upload.json").exists():
            up = UploadRecord.model_validate_json((cdir / "upload.json").read_text())
            st.uploaded, st.files, st.finished_at = up.uploaded, up.files, up.finished_at
            if up.error:
                st.error = f"upload: {up.error}"
        if (cdir / "report.json").exists():
            try:
                st.report = AnalysisReport.model_validate_json((cdir / "report.json").read_text())
                st.status = st.report.status
                st.error = st.report.error or st.error
            except ValueError as e:
                st.status, st.error = "failed", f"unreadable report: {e}"
        elif (cdir / "failed.json").exists():
            failure = RunFailure.model_validate_json((cdir / "failed.json").read_text())
            st.status, st.error, st.finished_at = "failed", failure.error, failure.finished_at
        else:
            st.status, st.error = "failed", "no report and no failure record"
        return st

    def recover(self) -> int:
        """After a restart: every ``running.json`` is stale. Record the interruption."""
        n = 0
        root = self._sessions.sessions_dir
        for marker_path in root.glob("*/runs/GSE*/running.json") if root.exists() else []:
            marker = RunMarker.model_validate_json(marker_path.read_text())
            now = datetime.now(UTC)
            for name in marker.contrasts:
                cdir = marker_path.parent / name
                if not (cdir / "report.json").exists():
                    cdir.mkdir(parents=True, exist_ok=True)
                    write_json(
                        cdir / "failed.json",
                        RunFailure(error="interrupted by server restart", finished_at=now),
                    )
                    n += 1
            marker_path.unlink()
        return n

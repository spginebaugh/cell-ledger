"""Pipeline runs inside a session: ``cell-ledger run`` as a subprocess, state in Postgres.

Rows: one ``runs`` row per (session, GSE) holds the design and the process lifecycle
(``running`` -> ``finished``); one ``run_contrasts`` row per contrast holds its verdict.
Files: the pipeline works in the local cache and the finished contrast folder is mirrored
to Storage at ``<session>/runs/<GSE>/<contrast>/<file>``::

    <session>/runs/<GSE>/design.json         what was submitted, as `--design` reads it
    <session>/runs/<GSE>/run.log             subprocess stdout + stderr
    <session>/runs/<GSE>/<contrast>/report.json   written by the pipeline

The subprocess keeps scanpy and pydeseq2 out of the API process: memory is returned when
the run ends and a crash cannot take the server down. A semaphore caps concurrent runs
because each fit wants a few GB. Clients poll :meth:`RunService.statuses`. A restart
re-dispatches running rows (see :meth:`RunService.recover`).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import sys
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import IO, Any, Literal

import asyncpg
import httpx
from pydantic import BaseModel, Field

from cell_ledger.progress import parse_progress_line
from cell_ledger.report.models import AnalysisReport
from cell_ledger_api.designs import RunRequest as RunRequest
from cell_ledger_api.sessions import SessionService, upload_dir

log = logging.getLogger(__name__)

DEFAULT_COMMAND: tuple[str, ...] = (sys.executable, "-m", "cell_ledger.cli")


RunState = Literal["running", "complete", "qc_only", "blocked", "failed"]
StepState = Literal["running", "done"]


class StepProgress(BaseModel):
    name: str
    status: StepState
    started_at: datetime
    seconds: float | None = None


class RunProgress(BaseModel):
    """Live view of a running contrast, rebuilt from the pipeline's progress lines."""

    started_at: datetime
    updated_at: datetime
    current: str | None = Field(default=None, description="step in progress, if any")
    steps: list[StepProgress] = Field(default_factory=list)
    queued: bool = Field(
        default=True, description="true until the pipeline has started this contrast"
    )

    def apply(self, event: dict[str, Any]) -> None:
        at = _when(event.get("at"))
        self.updated_at = at
        kind, status = event.get("event"), event.get("status")
        if kind == "run" and status == "started":
            self.queued = False
        elif kind == "step":
            name = str(event.get("name", ""))
            if status == "started":
                self.queued = False
                self.current = name
                self.steps.append(StepProgress(name=name, status="running", started_at=at))
            elif status == "finished":
                for st in reversed(self.steps):
                    if st.name == name and st.status == "running":
                        st.status, st.seconds = "done", event.get("seconds")
                        break
                if self.current == name:
                    self.current = None
        elif kind == "run" and status == "finished":
            self.current = None


def _when(value: Any) -> datetime:
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            pass
    return datetime.now(UTC)


class RunStatus(BaseModel):
    gse: str
    contrast: str
    status: RunState
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = Field(default=None, description="pipeline error or why the run failed")
    report: AnalysisReport | None = None
    progress: RunProgress | None = Field(
        default=None, description="step-by-step progress while running; null otherwise"
    )
    uploaded: bool = False
    upload_error: str | None = None
    files: list[str] = Field(default_factory=list, description="names available for signed URLs")


class RunView(RunStatus):
    """Everything the run page needs in one response."""

    design: RunRequest | None = Field(default=None, description="what was submitted")
    urls: dict[str, str] = Field(
        default_factory=dict, description="file name -> signed download URL"
    )
    urls_expire_in: int = 0


class RunNotFound(LookupError):
    pass


class RunConflict(RuntimeError):
    pass


class CountsMissing(LookupError):
    pass


def run_status(row: asyncpg.Record) -> RunStatus:
    st = RunStatus(
        gse=row["gse"],
        contrast=row["contrast"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        uploaded=row["uploaded"],
        upload_error=row["upload_error"],
        files=list(row["files"]),
    )
    if row["report"]:
        try:
            st.report = AnalysisReport.model_validate(row["report"])
        except ValueError as e:
            st.status, st.error = "failed", f"unreadable report: {e}"
    if row["progress"] and st.status == "running":
        try:
            st.progress = RunProgress.model_validate(row["progress"])
        except ValueError:
            st.progress = None
    return st


class RunService:
    def __init__(
        self,
        sessions: SessionService,
        *,
        max_concurrent: int = 2,
        n_cpus: int | None = None,
        timeout_minutes: float = 30,
        command: Sequence[str] = DEFAULT_COMMAND,
        max_attempts: int = 2,
    ) -> None:
        self._sessions = sessions
        self._db = sessions.db
        self._sem = asyncio.Semaphore(max_concurrent)
        self._n_cpus = n_cpus
        self._timeout = timeout_minutes * 60
        self._command = tuple(command)
        self._max_attempts = max_attempts
        # Set by the pipeline: called with the session id when a run (all its contrasts) ends.
        self.on_run_finished: Callable[[str], Awaitable[None]] | None = None

    async def _finished(self, session_id: str) -> None:
        if self.on_run_finished is None:
            return
        try:
            await self.on_run_finished(session_id)
        except Exception:  # the hook must never take the run down with it
            log.exception("run-finished hook failed for %s", session_id)

    def runs_dir(self, session_id: str) -> Path:
        return self._sessions.local(session_id) / "runs"

    # ------------------------------------------------------------- start

    async def start(self, session_id: str, req: RunRequest) -> list[RunStatus]:
        gse = req.samplesheet.gse
        await self._sessions.get(session_id)
        counts = await self._sessions.counts_path(session_id, gse)
        if counts is None:
            raise CountsMissing(f"{gse} has no collected counts in this session")
        await self._sessions.ensure_annotation()
        names = [c.name for c in req.contrasts]
        if not await self._db.start_run(session_id, gse, req.model_dump(mode="json"), names):
            raise RunConflict(f"a run for {gse} is already in progress")
        self._sessions.spawn(self._run(session_id, gse, counts, req))
        return [s for s in await self.statuses(session_id) if s.gse == gse and s.contrast in names]

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
        argv.append("--progress")
        return argv

    async def _run(self, session_id: str, gse: str, counts: Path, req: RunRequest) -> None:
        out = self.runs_dir(session_id) / gse
        out.mkdir(parents=True, exist_ok=True)
        for c in req.contrasts:  # a stale report must never be read as this run's result
            shutil.rmtree(out / c.name, ignore_errors=True)
        (out / "design.json").write_text(req.model_dump_json(indent=2))
        error: str | None = None
        now = datetime.now(UTC)
        progress = {
            c.name: RunProgress(started_at=now, updated_at=now, queued=True) for c in req.contrasts
        }
        async with self._sem:
            with (out / "run.log").open("ab") as logf:
                proc = await asyncio.create_subprocess_exec(
                    *self._argv(gse, out, counts, req),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                )
                assert proc.stdout is not None
                tail = asyncio.create_task(self._tail(proc.stdout, logf, session_id, gse, progress))
                try:
                    rc = await asyncio.wait_for(proc.wait(), timeout=self._timeout)
                except TimeoutError:
                    proc.kill()
                    await proc.wait()
                    error = f"killed after {self._timeout / 60:g} minutes"
                else:
                    if rc not in (0, 1):  # 1 = ran but not 'complete'; the report says why
                        error = f"pipeline exited with code {rc}; see run.log"
                await tail
        for contrast in req.contrasts:
            await self._finish_contrast(session_id, gse, out / contrast.name, error)
        await self._db.finish_run(session_id, gse, error)
        await self._finished(session_id)

    async def _tail(
        self,
        stream: asyncio.StreamReader,
        logf: IO[bytes],
        session_id: str,
        gse: str,
        progress: dict[str, RunProgress],
    ) -> None:
        """Copy the subprocess output to run.log and turn progress lines into row updates."""
        async for raw in stream:
            logf.write(raw)
            logf.flush()
            event = parse_progress_line(raw)
            if event is None:
                continue
            name = event.get("contrast")
            if name not in progress:
                continue
            progress[name].apply(event)
            try:
                await self._db.update_progress(
                    session_id, gse, name, progress[name].model_dump(mode="json")
                )
            except Exception:  # progress is advisory; never let it stop the run
                log.exception("could not store progress for %s/%s/%s", session_id, gse, name)

    async def _finish_contrast(
        self, session_id: str, gse: str, cdir: Path, run_error: str | None
    ) -> None:
        status: str = "failed"
        error: str | None = run_error or "pipeline wrote no report; see run.log"
        report: dict[str, Any] | None = None
        report_path = cdir / "report.json"
        if report_path.exists():
            try:
                parsed = AnalysisReport.model_validate_json(report_path.read_text())
                status, error, report = parsed.status, parsed.error, parsed.model_dump(mode="json")
            except ValueError as e:
                error = f"unreadable report: {e}"
        uploaded, upload_error, files = False, None, []
        if cdir.is_dir():
            try:
                files = await upload_dir(
                    self._sessions.store, f"{session_id}/runs/{gse}/{cdir.name}", cdir
                )
                uploaded = True
            except httpx.HTTPError as e:
                upload_error = f"{type(e).__name__}: {e}"
        await self._db.finish_contrast(
            session_id,
            gse,
            cdir.name,
            status=status,
            error=error,
            report=report,
            uploaded=uploaded,
            upload_error=upload_error,
            files=files,
        )

    # ------------------------------------------------------------ status

    async def statuses(self, session_id: str) -> list[RunStatus]:
        await self._sessions.get(session_id)
        return [run_status(r) for r in await self._db.list_run_contrasts(session_id)]

    async def view(self, session_id: str, gse: str, contrast: str, *, url_ttl: int) -> RunView:
        """One contrast with its design and signed URLs for every stored file."""
        await self._sessions.get(session_id)
        row = await self._db.get_run_contrast(session_id, gse, contrast)
        if row is None:
            raise RunNotFound(f"{gse}/{contrast}")
        status = run_status(row)
        urls = await self._sessions.file_urls(
            session_id, f"runs/{gse}/{contrast}", status.files, url_ttl
        )
        design = None
        if row["design"]:
            try:
                design = RunRequest.model_validate(row["design"])
            except ValueError:
                design = None
        return RunView(
            **status.model_dump(), design=design, urls=urls, urls_expire_in=url_ttl if urls else 0
        )

    # ---------------------------------------------------------- recovery

    async def recover(self) -> int:
        """Re-dispatch every run a restart interrupted, up to ``max_attempts`` times.
        Counts come back from Storage if this machine lacks them. Returns the count."""
        n = 0
        for row in await self._db.claim_running_runs():
            sid, gse, attempts = row["session_id"], row["gse"], row["attempts"]
            contrasts: list[str] = list(row["contrasts"])
            if attempts > self._max_attempts:
                await self._fail_all(
                    sid, gse, contrasts, f"interrupted by server restart {attempts - 1} times"
                )
                continue
            self._sessions.spawn(self._resume(sid, gse, RunRequest.model_validate(row["design"])))
            n += 1
        return n

    async def _resume(self, session_id: str, gse: str, req: RunRequest) -> None:
        try:
            counts = await self._sessions.counts_path(session_id, gse)
            await self._sessions.ensure_annotation()
        except httpx.HTTPError as e:
            counts = None
            log.warning("resume %s/%s: could not fetch inputs: %s", session_id, gse, e)
        if counts is None:
            names = [c.name for c in req.contrasts]
            await self._fail_all(session_id, gse, names, "interrupted by restart; counts missing")
            return
        await self._run(session_id, gse, counts, req)

    async def _fail_all(self, session_id: str, gse: str, contrasts: list[str], why: str) -> None:
        for name in contrasts:
            await self._db.finish_contrast(
                session_id,
                gse,
                name,
                status="failed",
                error=why,
                report=None,
                uploaded=False,
                upload_error=None,
                files=[],
            )
        await self._db.finish_run(session_id, gse, why)
        await self._finished(session_id)

"""Cross-dataset comparisons inside a session: ``cell-ledger run-set --compare-only`` as a
subprocess over the session's finished runs, state in Postgres.

One ``comparisons`` row per (session, name) holds the QuerySet that was submitted and the
``ComparisonReport`` it produced. Files mirror to ``<session>/comparisons/<name>/<file>``.
Member run directories are the pipeline's local outputs; whatever this machine lacks is
pulled back from Storage first (``report.json``, ``de_results.tsv``, ``enrichment.tsv``),
so a comparison works on a fresh machine as long as the runs were uploaded.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

import asyncpg
import httpx
from pydantic import BaseModel, Field

from cell_ledger.compare import ComparisonReport, QuerySet, QuerySetMember
from cell_ledger.report.models import MarkerExpectation
from cell_ledger_api.runs import DEFAULT_COMMAND, RunService
from cell_ledger_api.sessions import SessionService, upload_dir

log = logging.getLogger(__name__)

COMPARISON_JSON = "comparison.json"
# What a member needs on disk for the comparison to read it.
MEMBER_FILES = ("report.json", "de_results.tsv", "enrichment.tsv")


class CompareRequest(BaseModel):
    """A QuerySet over runs in this session, plus the few parameters a user may set."""

    name: str = Field(pattern=r"^[a-z0-9]+(_[a-z0-9]+)*$", description="slug")
    question: str = Field(min_length=1, max_length=1000)
    case_label: str = Field(min_length=1)
    control_label: str = Field(min_length=1)
    members: list[QuerySetMember] = Field(min_length=2)
    genes_of_interest: list[str] = Field(default_factory=list)
    markers: list[MarkerExpectation] = Field(default_factory=list)
    alpha: float = Field(default=0.05, gt=0, lt=1)
    min_studies: int = Field(default=3, ge=2)
    permutations: int = Field(default=1000, ge=10, le=10000)
    pooled_enrichment: bool = True

    def query_set(self) -> QuerySet:
        return QuerySet(
            name=self.name,
            question=self.question,
            case_label=self.case_label,
            control_label=self.control_label,
            members=self.members,
            markers=self.markers,
            genes_of_interest=self.genes_of_interest,
        )


CompareState = Literal["running", "complete", "insufficient", "failed"]


class ComparisonStatus(BaseModel):
    name: str
    status: CompareState
    started_at: datetime
    finished_at: datetime | None = None
    error: str | None = None
    request: CompareRequest
    report: ComparisonReport | None = None
    uploaded: bool = False
    upload_error: str | None = None
    files: list[str] = Field(default_factory=list, description="names available for signed URLs")


class ComparisonView(ComparisonStatus):
    urls: dict[str, str] = Field(default_factory=dict, description="file name -> signed URL")
    urls_expire_in: int = 0


class ComparisonConflict(RuntimeError):
    pass


class ComparisonNotFound(LookupError):
    pass


class MembersNotReady(LookupError):
    pass


def comparison_status(row: asyncpg.Record) -> ComparisonStatus:
    st = ComparisonStatus(
        name=row["name"],
        status=row["status"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        error=row["error"],
        request=CompareRequest.model_validate(row["request"]),
        uploaded=row["uploaded"],
        upload_error=row["upload_error"],
        files=list(row["files"]),
    )
    if row["report"]:
        try:
            st.report = ComparisonReport.model_validate(row["report"])
        except ValueError as e:
            st.status, st.error = "failed", f"unreadable report: {e}"
    return st


class CompareService:
    def __init__(
        self,
        sessions: SessionService,
        runs: RunService,
        *,
        timeout_minutes: float = 15,
        command: Sequence[str] = DEFAULT_COMMAND,
        max_concurrent: int = 1,
    ) -> None:
        self._sessions = sessions
        self._runs = runs
        self._db = sessions.db
        self._timeout = timeout_minutes * 60
        self._command = tuple(command)
        self._sem = asyncio.Semaphore(max_concurrent)

    def comparisons_dir(self, session_id: str) -> Path:
        return self._sessions.local(session_id) / "comparisons"

    # ------------------------------------------------------------- start

    async def start(self, session_id: str, req: CompareRequest) -> ComparisonStatus:
        await self._sessions.get(session_id)
        statuses = {(s.gse, s.contrast): s for s in await self._runs.statuses(session_id)}
        missing = [
            f"{m.gse}/{m.contrast}" for m in req.members if (m.gse, m.contrast) not in statuses
        ]
        if missing:
            raise MembersNotReady(f"no run in this session for {missing}")
        running = [
            f"{m.gse}/{m.contrast}"
            for m in req.members
            if statuses[(m.gse, m.contrast)].status == "running"
        ]
        if running:
            raise MembersNotReady(f"still running: {running}")
        if not await self._db.start_comparison(session_id, req.name, req.model_dump(mode="json")):
            raise ComparisonConflict(f"comparison {req.name!r} is already running")
        self._sessions.spawn(self._run(session_id, req))
        row = await self._db.get_comparison(session_id, req.name)
        assert row is not None
        return comparison_status(row)

    async def _ensure_member_files(self, session_id: str, member: QuerySetMember) -> None:
        """Pull a member's tables back from Storage when this machine does not have them."""
        local = self._runs.runs_dir(session_id) / member.gse / member.contrast
        for name in MEMBER_FILES:
            path = local / name
            if path.exists():
                continue
            await self._sessions.store.get_file(
                f"{session_id}/runs/{member.gse}/{member.contrast}/{name}", path
            )

    def _argv(
        self, req: CompareRequest, set_file: Path, runs_root: Path, out_root: Path
    ) -> list[str]:
        argv = [
            *self._command,
            "run-set",
            req.name,
            "--set-file",
            str(set_file),
            "--compare-only",
            "--out-root",
            str(runs_root),
            "--queries-root",
            str(out_root),
            "--alpha",
            str(req.alpha),
            "--min-studies",
            str(req.min_studies),
            "--permutations",
            str(req.permutations),
        ]
        if not req.pooled_enrichment:
            argv.append("--no-enrichment")
        return argv

    async def _run(self, session_id: str, req: CompareRequest) -> None:
        out_root = self.comparisons_dir(session_id)
        out_root.mkdir(parents=True, exist_ok=True)
        cdir = out_root / req.name
        set_file = out_root / f"{req.name}.queryset.json"
        set_file.write_text(req.query_set().model_dump_json(indent=2))
        error: str | None = None
        try:
            for m in req.members:
                await self._ensure_member_files(session_id, m)
        except httpx.HTTPError as e:
            error = f"could not fetch member runs from storage: {e}"
        if error is None:
            async with self._sem:
                with (out_root / f"{req.name}.log").open("ab") as logf:
                    proc = await asyncio.create_subprocess_exec(
                        *self._argv(req, set_file, self._runs.runs_dir(session_id), out_root),
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
                        if rc not in (0, 1):
                            error = f"comparison exited with code {rc}; see {req.name}.log"
        await self._finish(session_id, req.name, cdir, error)

    async def _finish(self, session_id: str, name: str, cdir: Path, run_error: str | None) -> None:
        status: str = "failed"
        error: str | None = run_error or "comparison wrote no report; see the log"
        report: dict[str, Any] | None = None
        path = cdir / COMPARISON_JSON
        if path.exists():
            try:
                parsed = ComparisonReport.model_validate_json(path.read_text())
                status, error, report = parsed.status, parsed.error, parsed.model_dump(mode="json")
                if run_error and status == "complete":
                    status, error = "failed", run_error
            except ValueError as e:
                error = f"unreadable report: {e}"
        uploaded, upload_error, files = False, None, []
        if cdir.is_dir():
            try:
                files = await upload_dir(
                    self._sessions.store, f"{session_id}/comparisons/{name}", cdir
                )
                uploaded = True
            except httpx.HTTPError as e:
                upload_error = f"{type(e).__name__}: {e}"
        await self._db.finish_comparison(
            session_id,
            name,
            status=status,
            error=error,
            report=report,
            uploaded=uploaded,
            upload_error=upload_error,
            files=files,
        )

    # ------------------------------------------------------------ status

    async def statuses(self, session_id: str) -> list[ComparisonStatus]:
        await self._sessions.get(session_id)
        return [comparison_status(r) for r in await self._db.list_comparisons(session_id)]

    async def view(self, session_id: str, name: str, *, url_ttl: int) -> ComparisonView:
        await self._sessions.get(session_id)
        row = await self._db.get_comparison(session_id, name)
        if row is None:
            raise ComparisonNotFound(name)
        status = comparison_status(row)
        urls = await self._sessions.file_urls(
            session_id, f"comparisons/{name}", status.files, url_ttl
        )
        return ComparisonView(
            **status.model_dump(), urls=urls, urls_expire_in=url_ttl if urls else 0
        )

    async def recover(self) -> int:
        return await self._db.fail_running_comparisons("interrupted by server restart")

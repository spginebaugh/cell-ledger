"""Ephemeral user sessions: collect GEO series into Postgres rows, Storage objects and a
local working folder.

Postgres is the source of truth (``sessions`` and ``datasets`` tables, see
``supabase/migrations``). Storage holds the files. The local layout below is a cache that
the downstream pipeline reads by path; anything missing is refetched from Storage or NCBI::

    <data_dir>/geo/annotation/Human.GRCh38.p13.annot.tsv.gz      shared, pulled once
    <data_dir>/sessions/<id>/geo/<GSE>/{counts, family.soft, dataset.json}
    <data_dir>/sessions/<id>/runs/...                            see runs.py

Collecting is a background task: the request inserts ``pending`` rows and returns; each
series becomes ``ready``, ``excluded`` or ``failed`` when its files are on disk and
mirrored to Storage at ``<id>/geo/<GSE>/<file>``. Clients poll :meth:`SessionService.datasets`.
After a restart, pending rows are re-dispatched (see :meth:`SessionService.recover`).
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

import asyncpg
import httpx
from pydantic import BaseModel, Field

from cell_ledger.geo import DatasetRecord, ensure_annotation, fetch_series
from cell_ledger.geo.fetch import ANNOTATION_NAME
from cell_ledger_api.db import Database
from cell_ledger_api.storage import SupabaseStore

log = logging.getLogger(__name__)

SESSION_ID = r"^[0-9a-f]{32}$"
CONTENT_TYPES = {
    ".gz": "application/gzip",
    ".json": "application/json",
    ".tsv": "text/tab-separated-values",
    ".csv": "text/csv",
    ".md": "text/markdown",
    ".txt": "text/plain",
    ".log": "text/plain",
    ".png": "image/png",
    ".h5ad": "application/octet-stream",
}


def content_type(path: Path) -> str:
    return CONTENT_TYPES.get(path.suffix, "application/octet-stream")


class SessionInfo(BaseModel):
    id: str
    created_at: datetime
    question: str | None = Field(default=None, description="what the user asked, if recorded")
    state: dict[str, Any] | None = Field(
        default=None,
        description="opaque UI state (discovery results, proposed designs); PATCH to replace",
    )


def session_info(row: asyncpg.Record) -> SessionInfo:
    return SessionInfo(
        id=row["id"], created_at=row["created_at"], question=row["question"], state=row["state"]
    )


DatasetState = Literal["pending", "ready", "excluded", "failed"]


class DatasetStatus(BaseModel):
    gse: str
    status: DatasetState = Field(description="pending while downloading; poll until it moves")
    record: DatasetRecord | None = Field(
        default=None, description="GEO metadata and checks; None while pending or when failed"
    )
    error: str | None = None
    uploaded: bool = False
    upload_error: str | None = None
    files: list[str] = Field(default_factory=list, description="names available for signed URLs")
    requested_at: datetime
    finished_at: datetime | None = None


class SessionNotFound(LookupError):
    pass


def dataset_status(row: asyncpg.Record) -> DatasetStatus:
    return DatasetStatus(
        gse=row["gse"],
        status=row["status"],
        record=DatasetRecord.model_validate(row["record"]) if row["record"] else None,
        error=row["error"],
        uploaded=row["uploaded"],
        upload_error=row["upload_error"],
        files=list(row["files"]),
        requested_at=row["requested_at"],
        finished_at=row["finished_at"],
    )


async def upload_dir(store: SupabaseStore, prefix: str, local: Path) -> list[str]:
    """Mirror every file under ``local`` (recursively) to ``prefix/<relative path>``."""
    names: list[str] = []
    for f in sorted(p for p in local.rglob("*") if p.is_file() and not p.name.endswith(".part")):
        rel = f.relative_to(local).as_posix()
        await store.put_file(f"{prefix}/{rel}", f, content_type(f))
        names.append(rel)
    return names


class SessionService:
    def __init__(
        self,
        db: Database,
        store: SupabaseStore,
        data_dir: Path,
        http: httpx.AsyncClient,
        *,
        max_concurrent: int = 3,
        max_attempts: int = 2,
    ) -> None:
        self.db = db
        self.store = store
        self.data_dir = data_dir
        self._http = http
        self._max_attempts = max_attempts
        self._sem = asyncio.Semaphore(max_concurrent)
        self._annotation_lock = asyncio.Lock()
        self._tasks: set[asyncio.Task[None]] = set()

    # ------------------------------------------------------------- paths

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def geo_root(self) -> Path:
        return self.data_dir / "geo"

    @property
    def annotation_path(self) -> Path:
        return self.geo_root / "annotation" / ANNOTATION_NAME

    def local(self, session_id: str) -> Path:
        """The session's cache folder (created on demand; the row is the real session)."""
        d = self.sessions_dir / session_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def ensure_annotation(self) -> None:
        async with self._annotation_lock:
            await ensure_annotation(self._http, self.geo_root)

    # ---------------------------------------------------------- sessions

    async def create(self) -> SessionInfo:
        row = await self.db.create_session(uuid.uuid4().hex)
        return SessionInfo(id=row["id"], created_at=row["created_at"])

    async def get(self, session_id: str) -> SessionInfo:
        row = await self.db.get_session(session_id)
        if row is None:
            raise SessionNotFound(session_id)
        return session_info(row)

    async def update(
        self, session_id: str, *, question: str | None, state: dict[str, Any] | None
    ) -> SessionInfo:
        row = await self.db.update_session(session_id, question=question, state=state)
        if row is None:
            raise SessionNotFound(session_id)
        return session_info(row)

    def spawn(self, coro) -> None:  # type: ignore[no-untyped-def]
        """Run a coroutine in the background; the task set keeps it alive."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ----------------------------------------------------------- collect

    async def collect(self, session_id: str, gses: list[str]) -> list[DatasetStatus]:
        """Start collecting; returns at once with every dataset's current status."""
        await self.get(session_id)
        for gse in await self.db.request_datasets(session_id, list(dict.fromkeys(gses))):
            self.spawn(self._collect_one(session_id, gse))
        return await self.datasets(session_id)

    async def _collect_one(self, session_id: str, gse: str) -> None:
        root = self.local(session_id) / "geo"
        local = root / gse
        record: DatasetRecord | None = None
        error: str | None = None
        try:
            await self.ensure_annotation()
            async with self._sem:
                record = await fetch_series(self._http, gse, root)
        except Exception as e:  # network, parse, disk: the dataset failed, not the session
            log.warning("collect %s/%s failed: %s", session_id, gse, e)
            error = f"{type(e).__name__}: {e}"
        uploaded, upload_error, files = False, None, []
        if local.is_dir():
            try:
                files = await upload_dir(self.store, f"{session_id}/geo/{gse}", local)
                uploaded = True
            except httpx.HTTPError as e:
                upload_error = f"{type(e).__name__}: {e}"
        await self.db.finish_dataset(
            session_id,
            gse,
            status=record.status if record else "failed",  # type: ignore[arg-type]
            record=record.model_dump(mode="json") if record else None,
            error=error,
            uploaded=uploaded,
            upload_error=upload_error,
            files=files,
        )

    async def datasets(self, session_id: str) -> list[DatasetStatus]:
        await self.get(session_id)
        return [dataset_status(r) for r in await self.db.list_datasets(session_id)]

    async def counts_path(self, session_id: str, gse: str) -> Path | None:
        """The collected counts file for a ready dataset, pulled from Storage if this
        machine does not have it; None when the dataset is not ready."""
        row = await self.db.get_dataset(session_id, gse)
        if row is None or row["status"] != "ready" or not row["record"]:
            return None
        rec = DatasetRecord.model_validate(row["record"])
        if "counts" not in rec.files:
            return None
        name = rec.files["counts"].name
        path = self.local(session_id) / "geo" / gse / name
        if not path.exists() and not await self.store.get_file(
            f"{session_id}/geo/{gse}/{name}", path
        ):
            return None
        return path

    # ------------------------------------------------------------- files

    async def file_url(self, session_id: str, rel: str, expires_in: int) -> str | None:
        """Signed URL for ``<session>/<rel>`` in Storage, e.g. ``geo/GSE1/dataset.json``."""
        await self.get(session_id)
        return await self.store.signed_url(f"{session_id}/{rel}", expires_in)

    async def file_urls(
        self, session_id: str, prefix: str, names: Sequence[str], expires_in: int
    ) -> dict[str, str]:
        """Signed URLs for many files under ``<session>/<prefix>/``, keyed by relative name.
        One Storage request; names missing from Storage are left out."""
        if not names:
            return {}
        full = [f"{session_id}/{prefix}/{n}" for n in names]
        signed = await self.store.signed_urls(full, expires_in)
        return {n: signed[f] for n, f in zip(names, full, strict=True) if f in signed}

    # --------------------------------------------------------- lifecycle

    async def delete(self, session_id: str) -> None:
        """Storage first (the only step that can fail and leave orphans), then the row
        (cascades to datasets and runs), then the local cache."""
        await self.get(session_id)
        await self.store.delete_prefix(session_id)
        await self.db.delete_session(session_id)
        shutil.rmtree(self.sessions_dir / session_id, ignore_errors=True)

    async def sweep(self, ttl: timedelta) -> list[str]:
        """Delete sessions older than ``ttl``; returns the ids removed. A session whose
        Storage delete fails is left for the next sweep."""
        removed: list[str] = []
        for sid in await self.db.expired_sessions(datetime.now(UTC) - ttl):
            try:
                await self.delete(sid)
            except httpx.HTTPError as e:
                log.warning("sweep: could not delete %s from storage: %s", sid, e)
                continue
            removed.append(sid)
        # Local folders whose row is gone (deleted from another machine, or before a crash).
        if self.sessions_dir.exists():
            for d in self.sessions_dir.iterdir():
                if d.is_dir() and await self.db.get_session(d.name) is None:
                    shutil.rmtree(d, ignore_errors=True)
        return removed

    async def recover(self) -> int:
        """Re-dispatch every download that a restart interrupted, up to ``max_attempts``
        times; after that the row is failed. Returns how many were re-dispatched."""
        n = 0
        for row in await self.db.claim_pending_datasets():
            sid, gse, attempts = row["session_id"], row["gse"], row["attempts"]
            if attempts > self._max_attempts:
                await self.db.finish_dataset(
                    sid,
                    gse,
                    status="failed",
                    record=None,
                    error=f"interrupted by server restart {attempts - 1} times; giving up",
                    uploaded=False,
                    upload_error=None,
                    files=[],
                )
                continue
            self.spawn(self._collect_one(sid, gse))
            n += 1
        return n

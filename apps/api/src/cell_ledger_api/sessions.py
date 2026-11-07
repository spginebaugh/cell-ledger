"""Ephemeral user sessions: collect GEO series into a working folder and object storage.

Local layout (what the downstream pipeline reads by path)::

    <data_dir>/geo/annotation/Human.GRCh38.p13.annot.tsv.gz      shared, pulled once
    <data_dir>/sessions/<id>/session.json                        SessionInfo (+ pending GSEs)
    <data_dir>/sessions/<id>/geo/<GSE>/{counts, family.soft, dataset.json}
    <data_dir>/sessions/<id>/geo/<GSE>/collected.json            CollectedDataset (API's view)
    <data_dir>/sessions/<id>/runs/...                            see runs.py

Collecting is a background task: the request records the accessions as ``pending`` and
returns; each series drops out of ``pending`` when its files and ``collected.json`` are
on disk (and mirrored to object storage at ``<id>/geo/<GSE>/<file>``). Clients poll
:meth:`SessionService.datasets`. State lives on disk, never only in memory, so a page
refresh sees the same thing and a restart can mark what was interrupted.
"""

from __future__ import annotations

import asyncio
import logging
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel, Field

from cell_ledger.geo import DatasetRecord, ensure_annotation, fetch_series
from cell_ledger.geo.fetch import ANNOTATION_NAME
from cell_ledger_api.storage import ObjectStore

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


def write_json(path: Path, model: BaseModel) -> None:
    """Write atomically so a poller never reads a half-written file."""
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(model.model_dump_json(indent=2))
    tmp.replace(path)


class SessionInfo(BaseModel):
    id: str
    created_at: datetime
    pending: list[str] = Field(
        default_factory=list, description="GSEs still being collected; poll until empty"
    )


class CollectedDataset(BaseModel):
    gse: str
    record: DatasetRecord | None = Field(
        default=None, description="None when the download itself failed; see error"
    )
    error: str | None = None
    uploaded: bool = False
    upload_error: str | None = None
    files: list[str] = Field(default_factory=list, description="names available for signed URLs")


class SessionDatasets(BaseModel):
    pending: list[str]
    datasets: list[CollectedDataset]


class SessionNotFound(LookupError):
    pass


async def upload_dir(store: ObjectStore, prefix: str, local: Path) -> list[str]:
    """Mirror every file under ``local`` (recursively) to ``prefix/<relative path>``."""
    names: list[str] = []
    for f in sorted(p for p in local.rglob("*") if p.is_file() and not p.name.endswith(".tmp")):
        rel = f.relative_to(local).as_posix()
        await store.put_file(f"{prefix}/{rel}", f, content_type(f))
        names.append(rel)
    return names


class SessionService:
    def __init__(
        self,
        data_dir: Path,
        http: httpx.AsyncClient,
        store: ObjectStore | None,
        *,
        max_concurrent: int = 3,
    ) -> None:
        self.data_dir = data_dir
        self._http = http
        self.store = store
        self._sem = asyncio.Semaphore(max_concurrent)
        self._annotation_lock = asyncio.Lock()
        self._info_lock = asyncio.Lock()
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

    def dir(self, session_id: str) -> Path:
        d = self.sessions_dir / session_id
        if not (d / "session.json").exists():
            raise SessionNotFound(session_id)
        return d

    # ---------------------------------------------------------- sessions

    def create(self) -> SessionInfo:
        info = SessionInfo(id=uuid.uuid4().hex, created_at=datetime.now(UTC))
        d = self.sessions_dir / info.id
        (d / "geo").mkdir(parents=True)
        write_json(d / "session.json", info)
        return info

    def get(self, session_id: str) -> SessionInfo:
        return SessionInfo.model_validate_json((self.dir(session_id) / "session.json").read_text())

    async def _update_pending(
        self, session_id: str, add: list[str] | None = None, remove: str | None = None
    ) -> SessionInfo:
        async with self._info_lock:
            info = self.get(session_id)
            pending = [g for g in info.pending if g != remove]
            pending += [g for g in add or [] if g not in pending]
            info.pending = pending
            write_json(self.dir(session_id) / "session.json", info)
            return info

    def spawn(self, coro) -> None:  # type: ignore[no-untyped-def]
        """Run a coroutine in the background; the task set keeps it alive."""
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    # ----------------------------------------------------------- collect

    async def collect(self, session_id: str, gses: list[str]) -> SessionInfo:
        """Start collecting; returns at once with the GSEs now pending."""
        info = self.get(session_id)
        new = [g for g in dict.fromkeys(gses) if g not in info.pending]
        info = await self._update_pending(session_id, add=new)
        for gse in new:
            self.spawn(self._collect_one(session_id, gse))
        return info

    async def _collect_one(self, session_id: str, gse: str) -> None:
        root = self.dir(session_id) / "geo"
        local = root / gse
        result = CollectedDataset(gse=gse)
        try:
            async with self._annotation_lock:
                await ensure_annotation(self._http, self.geo_root)
            async with self._sem:
                result.record = await fetch_series(self._http, gse, root)
        except Exception as e:  # network, parse, disk: the dataset failed, not the session
            log.warning("collect %s/%s failed: %s", session_id, gse, e)
            result.error = f"{type(e).__name__}: {e}"
        if self.store is not None and local.is_dir():
            try:
                result.files = await upload_dir(self.store, f"{session_id}/geo/{gse}", local)
                result.uploaded = True
            except httpx.HTTPError as e:
                result.upload_error = f"{type(e).__name__}: {e}"
        local.mkdir(parents=True, exist_ok=True)
        write_json(local / "collected.json", result)
        await self._update_pending(session_id, remove=gse)

    def datasets(self, session_id: str) -> SessionDatasets:
        root = self.dir(session_id) / "geo"
        return SessionDatasets(
            pending=self.get(session_id).pending,
            datasets=[
                CollectedDataset.model_validate_json(p.read_text())
                for p in sorted(root.glob("GSE*/collected.json"))
            ],
        )

    def counts_path(self, session_id: str, gse: str) -> Path | None:
        """The collected counts file for a ready dataset, else None."""
        p = self.dir(session_id) / "geo" / gse / "collected.json"
        if not p.exists():
            return None
        rec = CollectedDataset.model_validate_json(p.read_text()).record
        if rec is None or rec.status != "ready" or "counts" not in rec.files:
            return None
        return p.parent / rec.files["counts"].name

    # ------------------------------------------------------------- files

    async def file_url(self, session_id: str, rel: str, expires_in: int) -> str | None:
        """Signed URL for ``<session>/<rel>`` in object storage, e.g. ``geo/GSE1/dataset.json``."""
        self.dir(session_id)
        if self.store is None:
            return None
        return await self.store.signed_url(f"{session_id}/{rel}", expires_in)

    # --------------------------------------------------------- lifecycle

    async def delete(self, session_id: str) -> None:
        d = self.dir(session_id)
        if self.store is not None:
            await self.store.delete_prefix(session_id)
        shutil.rmtree(d)

    async def sweep(self, ttl: timedelta) -> list[str]:
        """Delete sessions older than ``ttl``; returns the ids removed."""
        if not self.sessions_dir.exists():
            return []
        cutoff = datetime.now(UTC) - ttl
        removed: list[str] = []
        for marker in self.sessions_dir.glob("*/session.json"):
            info = SessionInfo.model_validate_json(marker.read_text())
            if info.created_at < cutoff:
                try:
                    await self.delete(info.id)
                except httpx.HTTPError:
                    shutil.rmtree(marker.parent, ignore_errors=True)
                removed.append(info.id)
        return removed

    def recover(self) -> int:
        """After a restart nothing is in flight: clear every ``pending`` list and record the
        series that never finished. Returns how many GSEs were interrupted."""
        n = 0
        for marker in (
            self.sessions_dir.glob("*/session.json") if self.sessions_dir.exists() else []
        ):
            info = SessionInfo.model_validate_json(marker.read_text())
            for gse in info.pending:
                local = marker.parent / "geo" / gse
                if not (local / "collected.json").exists():
                    local.mkdir(parents=True, exist_ok=True)
                    write_json(
                        local / "collected.json",
                        CollectedDataset(gse=gse, error="interrupted by server restart"),
                    )
                    n += 1
            if info.pending:
                info.pending = []
                write_json(marker, info)
        return n

"""Ephemeral user sessions: collect GEO series into a working folder and object storage.

Local layout (what the downstream pipeline reads by path)::

    <data_dir>/geo/annotation/Human.GRCh38.p13.annot.tsv.gz      shared, pulled once
    <data_dir>/sessions/<id>/session.json
    <data_dir>/sessions/<id>/geo/<GSE>/{counts, family.soft, dataset.json}

The same per-series files are mirrored to object storage at ``<id>/geo/<GSE>/<file>``.
"""

from __future__ import annotations

import asyncio
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from pydantic import BaseModel

from cell_ledger.geo import DatasetRecord, ensure_annotation, fetch_series
from cell_ledger_api.storage import ObjectStore

SESSION_ID = r"^[0-9a-f]{32}$"
CONTENT_TYPES = {".gz": "application/gzip", ".json": "application/json"}


class SessionInfo(BaseModel):
    id: str
    created_at: datetime


class CollectedDataset(BaseModel):
    record: DatasetRecord
    local_dir: str
    uploaded: bool
    upload_error: str | None = None


class SessionNotFound(LookupError):
    pass


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
        self._store = store
        self._sem = asyncio.Semaphore(max_concurrent)
        self._annotation_lock = asyncio.Lock()

    @property
    def sessions_dir(self) -> Path:
        return self.data_dir / "sessions"

    @property
    def geo_root(self) -> Path:
        return self.data_dir / "geo"

    def _dir(self, session_id: str) -> Path:
        d = self.sessions_dir / session_id
        if not (d / "session.json").exists():
            raise SessionNotFound(session_id)
        return d

    def create(self) -> SessionInfo:
        info = SessionInfo(id=uuid.uuid4().hex, created_at=datetime.now(UTC))
        d = self.sessions_dir / info.id
        (d / "geo").mkdir(parents=True)
        (d / "session.json").write_text(info.model_dump_json())
        return info

    def get(self, session_id: str) -> SessionInfo:
        return SessionInfo.model_validate_json((self._dir(session_id) / "session.json").read_text())

    async def collect(self, session_id: str, gses: list[str]) -> list[CollectedDataset]:
        root = self._dir(session_id) / "geo"
        async with self._annotation_lock:
            await ensure_annotation(self._http, self.geo_root)
        unique = list(dict.fromkeys(gses))
        return list(await asyncio.gather(*(self._collect_one(session_id, root, g) for g in unique)))

    async def _collect_one(self, session_id: str, root: Path, gse: str) -> CollectedDataset:
        async with self._sem:
            record = await fetch_series(self._http, gse, root)
        local = root / gse
        uploaded, error = False, None
        if self._store is not None:
            try:
                for f in sorted(p for p in local.iterdir() if p.is_file()):
                    await self._store.put(
                        f"{session_id}/geo/{gse}/{f.name}",
                        f.read_bytes(),
                        CONTENT_TYPES.get(f.suffix, "application/octet-stream"),
                    )
                uploaded = True
            except httpx.HTTPError as e:
                error = f"{type(e).__name__}: {e}"
        return CollectedDataset(
            record=record, local_dir=str(local), uploaded=uploaded, upload_error=error
        )

    def datasets(self, session_id: str) -> list[DatasetRecord]:
        root = self._dir(session_id) / "geo"
        return [
            DatasetRecord.model_validate_json(p.read_text())
            for p in sorted(root.glob("GSE*/dataset.json"))
        ]

    async def file_url(self, session_id: str, gse: str, name: str, expires_in: int) -> str | None:
        self._dir(session_id)
        if self._store is None:
            return None
        return await self._store.signed_url(f"{session_id}/geo/{gse}/{name}", expires_in)

    async def delete(self, session_id: str) -> None:
        d = self._dir(session_id)
        if self._store is not None:
            await self._store.delete_prefix(session_id)
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

"""Postgres access: the single source of truth for sessions, datasets and runs.

One :class:`Database` wraps an asyncpg pool and holds every SQL statement the API runs,
so the services in ``sessions.py`` and ``runs.py`` read as workflow, not as queries. The
schema is ``supabase/migrations``; rows carry the pydantic models as ``jsonb``.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime
from typing import Any, Self

import asyncpg

MAX_ATTEMPTS_DEFAULT = 2


async def _init_connection(conn: asyncpg.Connection) -> None:
    # jsonb <-> dict so callers hand over model_dump(mode="json") and get dicts back.
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog", format="text"
    )


class Database:
    def __init__(self, pool: asyncpg.Pool) -> None:
        self._pool = pool

    @classmethod
    async def connect(cls, url: str, *, min_size: int = 1, max_size: int = 5) -> Self:
        # statement_cache_size=0 keeps us compatible with Supavisor's transaction pooler,
        # where prepared statements do not survive between transactions.
        pool = await asyncpg.create_pool(
            url,
            min_size=min_size,
            max_size=max_size,
            init=_init_connection,
            statement_cache_size=0,
            command_timeout=60,
        )
        assert pool is not None
        return cls(pool)

    async def close(self) -> None:
        await self._pool.close()

    async def ping(self) -> None:
        await self._pool.fetchval("select 1")

    # ---------------------------------------------------------------- sessions

    async def create_session(self, session_id: str) -> asyncpg.Record:
        return await self._pool.fetchrow(
            "insert into sessions (id) values ($1) returning id, created_at", session_id
        )  # type: ignore[return-value]

    async def get_session(self, session_id: str) -> asyncpg.Record | None:
        return await self._pool.fetchrow(
            "select id, created_at, question, state from sessions where id = $1", session_id
        )

    async def update_session(
        self, session_id: str, *, question: str | None, state: dict[str, Any] | None
    ) -> asyncpg.Record | None:
        """Set what is given (None leaves a column alone) and return the row."""
        return await self._pool.fetchrow(
            """
            update sessions
               set question = coalesce($2, question), state = coalesce($3, state)
             where id = $1
            returning id, created_at, question, state
            """,
            session_id,
            question,
            state,
        )

    async def delete_session(self, session_id: str) -> bool:
        tag = await self._pool.execute("delete from sessions where id = $1", session_id)
        return tag == "DELETE 1"

    async def expired_sessions(self, cutoff: datetime) -> list[str]:
        rows = await self._pool.fetch("select id from sessions where created_at < $1", cutoff)
        return [r["id"] for r in rows]

    # ---------------------------------------------------------------- datasets

    async def request_datasets(self, session_id: str, gses: Sequence[str]) -> list[str]:
        """Mark ``gses`` pending and return the ones that need a download.

        New accessions are inserted; failed ones are reset for another try; ready, excluded
        and already-pending rows are left alone and not returned, so a duplicate request
        never starts a second download.
        """
        rows = await self._pool.fetch(
            """
            insert into datasets (session_id, gse, status)
            select $1, g, 'pending' from unnest($2::text[]) as g
            on conflict (session_id, gse) do update
              set status = 'pending', attempts = 0, error = null, record = null,
                  uploaded = false, upload_error = null, files = '{}',
                  requested_at = now(), finished_at = null
              where datasets.status = 'failed'
            returning gse
            """,
            session_id,
            list(gses),
        )
        return [r["gse"] for r in rows]

    async def finish_dataset(
        self,
        session_id: str,
        gse: str,
        *,
        status: str,
        record: dict[str, Any] | None,
        error: str | None,
        uploaded: bool,
        upload_error: str | None,
        files: Sequence[str],
    ) -> None:
        await self._pool.execute(
            """
            update datasets
               set status = $3, record = $4, error = $5, uploaded = $6, upload_error = $7,
                   files = $8, finished_at = now()
             where session_id = $1 and gse = $2
            """,
            session_id,
            gse,
            status,
            record,
            error,
            uploaded,
            upload_error,
            list(files),
        )

    async def list_datasets(self, session_id: str) -> list[asyncpg.Record]:
        return await self._pool.fetch(
            "select * from datasets where session_id = $1 order by gse", session_id
        )

    async def get_dataset(self, session_id: str, gse: str) -> asyncpg.Record | None:
        return await self._pool.fetchrow(
            "select * from datasets where session_id = $1 and gse = $2", session_id, gse
        )

    async def claim_pending_datasets(self) -> list[asyncpg.Record]:
        """Every pending row, with ``attempts`` bumped: called once at boot, when no
        download can be in flight, so each row belongs to this process afterwards."""
        return await self._pool.fetch(
            """
            update datasets set attempts = attempts + 1
             where status = 'pending'
            returning session_id, gse, attempts
            """
        )

    # -------------------------------------------------------------------- runs

    async def start_run(
        self, session_id: str, gse: str, design: dict[str, Any], contrasts: Sequence[str]
    ) -> bool:
        """Record a new run and reset its contrasts to running. False when one is already
        running for this GSE (the caller reports a conflict)."""
        async with self._pool.acquire() as conn, conn.transaction():
            row = await conn.fetchrow(
                """
                insert into runs (session_id, gse, status, design)
                values ($1, $2, 'running', $3)
                on conflict (session_id, gse) do update
                  set status = 'running', attempts = 0, design = excluded.design,
                      started_at = now(), finished_at = null, error = null
                  where runs.status <> 'running'
                returning gse
                """,
                session_id,
                gse,
                design,
            )
            if row is None:
                return False
            await conn.execute(
                """
                insert into run_contrasts (session_id, gse, contrast, status, design)
                select $1, $2, c, 'running', $4 from unnest($3::text[]) as c
                on conflict (session_id, gse, contrast) do update
                  set status = 'running', started_at = now(), finished_at = null,
                      error = null, report = null, uploaded = false, upload_error = null,
                      files = '{}', progress = null, design = excluded.design
                """,
                session_id,
                gse,
                list(contrasts),
                design,
            )
        return True

    async def finish_contrast(
        self,
        session_id: str,
        gse: str,
        contrast: str,
        *,
        status: str,
        error: str | None,
        report: dict[str, Any] | None,
        uploaded: bool,
        upload_error: str | None,
        files: Sequence[str],
    ) -> None:
        await self._pool.execute(
            """
            update run_contrasts
               set status = $4, error = $5, report = $6, uploaded = $7, upload_error = $8,
                   files = $9, finished_at = now(), progress = null
             where session_id = $1 and gse = $2 and contrast = $3
            """,
            session_id,
            gse,
            contrast,
            status,
            error,
            report,
            uploaded,
            upload_error,
            list(files),
        )

    async def update_progress(
        self, session_id: str, gse: str, contrast: str, progress: dict[str, Any]
    ) -> None:
        """Replace the live progress of a contrast that is still running."""
        await self._pool.execute(
            """
            update run_contrasts set progress = $4
             where session_id = $1 and gse = $2 and contrast = $3 and status = 'running'
            """,
            session_id,
            gse,
            contrast,
            progress,
        )

    async def get_run_contrast(
        self, session_id: str, gse: str, contrast: str
    ) -> asyncpg.Record | None:
        # c.design is the design this contrast's report came from; r.design is whatever the
        # latest run of the GSE submitted and may no longer describe this contrast.
        return await self._pool.fetchrow(
            """
            select c.*, r.error as run_error
              from run_contrasts c join runs r using (session_id, gse)
             where c.session_id = $1 and c.gse = $2 and c.contrast = $3
            """,
            session_id,
            gse,
            contrast,
        )

    async def finish_run(self, session_id: str, gse: str, error: str | None) -> None:
        await self._pool.execute(
            """
            update runs set status = 'finished', finished_at = now(), error = $3
             where session_id = $1 and gse = $2
            """,
            session_id,
            gse,
            error,
        )

    async def list_run_contrasts(self, session_id: str) -> list[asyncpg.Record]:
        return await self._pool.fetch(
            """
            select c.*, r.error as run_error
              from run_contrasts c join runs r using (session_id, gse)
             where c.session_id = $1
             order by c.gse, c.contrast
            """,
            session_id,
        )

    async def claim_running_runs(self) -> list[asyncpg.Record]:
        """Every running row with ``attempts`` bumped; boot-time only, like
        :meth:`claim_pending_datasets`. Includes the contrasts still marked running."""
        return await self._pool.fetch(
            """
            with claimed as (
              update runs set attempts = attempts + 1
               where status = 'running'
              returning session_id, gse, design, attempts
            )
            select cl.*, array_agg(c.contrast order by c.contrast) as contrasts
              from claimed cl
              join run_contrasts c using (session_id, gse)
             where c.status = 'running'
             group by cl.session_id, cl.gse, cl.design, cl.attempts
            """
        )

    # ------------------------------------------------------------- comparisons

    async def start_comparison(self, session_id: str, name: str, request: dict[str, Any]) -> bool:
        """Record a new comparison, or restart a finished one. False while one is running."""
        row = await self._pool.fetchrow(
            """
            insert into comparisons (session_id, name, status, request)
            values ($1, $2, 'running', $3)
            on conflict (session_id, name) do update
              set status = 'running', request = excluded.request, started_at = now(),
                  finished_at = null, error = null, report = null, uploaded = false,
                  upload_error = null, files = '{}'
              where comparisons.status <> 'running'
            returning name
            """,
            session_id,
            name,
            request,
        )
        return row is not None

    async def finish_comparison(
        self,
        session_id: str,
        name: str,
        *,
        status: str,
        error: str | None,
        report: dict[str, Any] | None,
        uploaded: bool,
        upload_error: str | None,
        files: Sequence[str],
    ) -> None:
        await self._pool.execute(
            """
            update comparisons
               set status = $3, error = $4, report = $5, uploaded = $6, upload_error = $7,
                   files = $8, finished_at = now()
             where session_id = $1 and name = $2
            """,
            session_id,
            name,
            status,
            error,
            report,
            uploaded,
            upload_error,
            list(files),
        )

    async def list_comparisons(self, session_id: str) -> list[asyncpg.Record]:
        return await self._pool.fetch(
            "select * from comparisons where session_id = $1 order by started_at", session_id
        )

    async def get_comparison(self, session_id: str, name: str) -> asyncpg.Record | None:
        return await self._pool.fetchrow(
            "select * from comparisons where session_id = $1 and name = $2", session_id, name
        )

    async def fail_running_comparisons(self, why: str) -> int:
        """Boot-time: a comparison interrupted by a restart is simply failed (it is cheap to
        rerun and holds no partial state worth resuming)."""
        tag = await self._pool.execute(
            """
            update comparisons set status = 'failed', error = $1, finished_at = now()
             where status = 'running'
            """,
            why,
        )
        return int(tag.split()[-1]) if tag.startswith("UPDATE") else 0

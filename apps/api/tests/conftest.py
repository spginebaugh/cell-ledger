"""Shared fixtures: a fake GEO host, the real local Supabase stack, and poll helpers.

Postgres and Storage are never faked. Tests run against the stack `mise run supabase:start`
boots, which applies the same migrations and bucket as the cloud project, so what passes
here is what runs on Fly. GEO is faked because NCBI is not something we emulate.

Every session a test creates (through the API or straight into the tables) is deleted at
teardown, rows and objects both, so the dev stack stays clean.
"""

from __future__ import annotations

import asyncio
import gzip
import os
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import asyncpg
import httpx
import pytest
from fastapi.testclient import TestClient

from cell_ledger.geo.fetch import ANNOTATION_URL, counts_url, soft_url
from cell_ledger_api.main import create_app
from cell_ledger_api.runs import DEFAULT_COMMAND
from cell_ledger_api.settings import Settings
from cell_ledger_api.storage import SupabaseStore

# The local stack's fixed addresses (supabase/config.toml) and its fixed service_role key.
# That key is the Supabase CLI's public demo default: it only works against a local stack.
LOCAL_DB_URL = "postgresql://postgres:postgres@127.0.0.1:57322/postgres"
LOCAL_SUPABASE_URL = "http://127.0.0.1:57321"
LOCAL_SECRET_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZS1kZW1vIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIsImV4cCI6MTk4MzgxMjk5Nn0."
    "EGIM96RAZx35lJzdJsyH-qQwv8Hdp7fsn3W0YpN81IU"
)
START_HINT = "run `mise run supabase:start` first"


def local_settings(**overrides: Any) -> Settings:
    db_url = os.environ.get("CELL_LEDGER_TEST_DATABASE_URL", LOCAL_DB_URL)
    host = urlparse(db_url).hostname
    if host not in ("127.0.0.1", "localhost"):
        pytest.fail(f"tests only run against a local stack, not {host}")
    return Settings(
        _env_file=None,  # type: ignore[call-arg]
        database_url=db_url,
        supabase_url=os.environ.get("CELL_LEDGER_TEST_SUPABASE_URL", LOCAL_SUPABASE_URL),
        supabase_secret_key=os.environ.get(
            "CELL_LEDGER_TEST_SUPABASE_SECRET_KEY", LOCAL_SECRET_KEY
        ),
        **overrides,
    )


def store_for(cfg: Settings) -> SupabaseStore:
    return SupabaseStore(
        cfg.supabase_url, cfg.supabase_secret_key.get_secret_value(), cfg.supabase_bucket
    )


async def _probe(cfg: Settings) -> None:
    conn = await asyncpg.connect(cfg.database_url.get_secret_value(), timeout=5)
    try:
        tables = {
            r["table_name"]
            for r in await conn.fetch(
                "select table_name from information_schema.tables where table_schema = 'public'"
            )
        }
    finally:
        await conn.close()
    missing = {"sessions", "datasets", "runs", "run_contrasts"} - tables
    if missing:
        pytest.fail(f"schema missing tables {sorted(missing)}: run `supabase db reset`")
    store = store_for(cfg)
    try:
        await store.check()
    finally:
        await store.aclose()


@pytest.fixture(scope="session", autouse=True)
def local_stack() -> None:
    """Fail the whole run, with instructions, when the local Supabase stack is down."""
    try:
        asyncio.run(_probe(local_settings()))
    except (OSError, asyncpg.PostgresError, httpx.HTTPError, RuntimeError) as e:
        pytest.fail(f"local Supabase stack not reachable ({type(e).__name__}: {e}); {START_HINT}")


# ------------------------------------------------------------------ fake GEO

SOFT = """\
^SERIES = GSE100001
!Series_title = Drug X in PANC-1 cells
^SAMPLE = GSM1
!Sample_organism_ch1 = Homo sapiens
!Sample_library_strategy = RNA-Seq
^SAMPLE = GSM2
!Sample_organism_ch1 = Mus musculus
!Sample_library_strategy = RNA-Seq
"""
GEO_FILES = {
    ANNOTATION_URL: gzip.compress(b"GeneID\tSymbol\n1\tA1BG\n"),
    counts_url("GSE100001"): gzip.compress(b"GeneID\tGSM1\tGSM2\n1\t5\t6\n"),
    soft_url("GSE100001"): gzip.compress(SOFT.encode()),
    # GSE100003: counts exist, the SOFT file does not -> the download error path.
    counts_url("GSE100003"): gzip.compress(b"GeneID\tGSM1\n1\t5\n"),
}


def fake_geo(request: httpx.Request) -> httpx.Response:
    url = str(request.url)
    if "esearch.fcgi" in url:
        return httpx.Response(200, json={"esearchresult": {"count": "0", "idlist": []}})
    if url in GEO_FILES:
        return httpx.Response(200, content=b"" if request.method == "HEAD" else GEO_FILES[url])
    return httpx.Response(404)


@pytest.fixture
def geo_transport() -> httpx.MockTransport:
    return httpx.MockTransport(fake_geo)


# ------------------------------------------------------------ app + cleanup

ApiFactory = Callable[..., Any]


@pytest.fixture
def settings_for(tmp_path: Path) -> Callable[..., Settings]:
    """Local-stack settings with the test's temp dir as the file cache."""
    return lambda **kw: local_settings(data_dir=tmp_path, **kw)


@pytest.fixture
def pg(settings_for: Callable[..., Settings]) -> Callable[..., Any]:
    """Run one statement against the stack: ``pg("select ...", arg, ...)`` -> records."""
    url = settings_for().database_url.get_secret_value()

    async def _run(sql: str, *args: Any) -> list[asyncpg.Record]:
        conn = await asyncpg.connect(url)
        try:
            return await conn.fetch(sql, *args)
        finally:
            await conn.close()

    return lambda sql, *args: asyncio.run(_run(sql, *args))


async def _db_now(cfg: Settings) -> datetime:
    """The database's clock: rows are stamped with it, and it may differ from the host's."""
    conn = await asyncpg.connect(cfg.database_url.get_secret_value())
    try:
        return await conn.fetchval("select now()")
    finally:
        await conn.close()


async def _cleanup(cfg: Settings, since: datetime) -> None:
    conn = await asyncpg.connect(cfg.database_url.get_secret_value())
    store = store_for(cfg)
    try:
        ids = [
            r["id"]
            for r in await conn.fetch("select id from sessions where created_at >= $1", since)
        ]
        for sid in ids:
            await store.delete_prefix(sid)
        await conn.execute("delete from sessions where id = any($1::text[])", ids)
    finally:
        await store.aclose()
        await conn.close()


@pytest.fixture
def api(
    settings_for: Callable[..., Settings], geo_transport: httpx.MockTransport
) -> Iterator[ApiFactory]:
    """``with api(**settings) as client`` boots the app against the local stack.

    Settings overrides go to :class:`Settings`; ``run_command``, ``compare_command`` and
    ``exa`` to :func:`create_app`. Sessions created during the test are removed afterwards.
    """
    started = asyncio.run(_db_now(settings_for()))

    @contextmanager
    def make(  # type: ignore[no-untyped-def]
        *,
        run_command: Any = DEFAULT_COMMAND,
        compare_command: Any = DEFAULT_COMMAND,
        exa: Any = None,
        turn: Any = None,
        **overrides: Any,
    ):
        app = create_app(
            settings_for(**overrides),
            transport=geo_transport,
            run_command=run_command,
            compare_command=compare_command,
            exa=exa,
            turn=turn,
        )
        with TestClient(app) as c:
            yield c

    yield make
    asyncio.run(_cleanup(settings_for(), started))


@pytest.fixture
def client(api: ApiFactory) -> Iterator[TestClient]:
    with api(max_datasets_per_request=2, run_timeout_minutes=0.02) as c:
        yield c


# ------------------------------------------------------------------ polling


def _wait_collected(client: TestClient, sid: str, timeout: float = 10) -> list[dict]:  # type: ignore[type-arg]
    """Poll listDatasets the way the UI does, until nothing is pending."""
    deadline = time.monotonic() + timeout
    while True:
        datasets = client.get(f"/api/sessions/{sid}/datasets").json()
        if all(d["status"] != "pending" for d in datasets):
            return datasets
        assert time.monotonic() < deadline, f"still pending: {datasets}"
        time.sleep(0.05)


@pytest.fixture
def wait_collected() -> Callable[..., list[dict]]:  # type: ignore[type-arg]
    return _wait_collected


def _wait_runs(client: TestClient, sid: str, timeout: float = 10) -> list[dict]:  # type: ignore[type-arg]
    deadline = time.monotonic() + timeout
    while True:
        runs = client.get(f"/api/sessions/{sid}/runs").json()
        if runs and all(r["status"] != "running" for r in runs):
            return runs
        assert time.monotonic() < deadline, runs
        time.sleep(0.05)


@pytest.fixture
def wait_runs() -> Callable[..., list[dict]]:  # type: ignore[type-arg]
    return _wait_runs

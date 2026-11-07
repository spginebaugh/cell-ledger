import logging
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cell_ledger.geo import GeoClient
from cell_ledger_api import __version__
from cell_ledger_api.routes import geo, health, runs, sessions
from cell_ledger_api.runs import DEFAULT_COMMAND, RunService
from cell_ledger_api.sessions import SessionNotFound, SessionService
from cell_ledger_api.settings import Settings, settings
from cell_ledger_api.spa import SpaMount, SpaStaticFiles
from cell_ledger_api.storage import ObjectStore, SupabaseStore

log = logging.getLogger("cell_ledger_api")


def _store(cfg: Settings, http: httpx.AsyncClient) -> ObjectStore | None:
    if cfg.supabase_url and cfg.supabase_secret_key:
        return SupabaseStore(
            http, cfg.supabase_url, cfg.supabase_secret_key.get_secret_value(), cfg.supabase_bucket
        )
    log.warning("Supabase not configured: session files stay on local disk only")
    return None


def create_app(
    cfg: Settings = settings,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    store: ObjectStore | None = None,
    run_command: Sequence[str] = DEFAULT_COMMAND,
) -> FastAPI:
    """``transport``, ``store`` and ``run_command`` let tests swap out GEO, Supabase and
    the pipeline subprocess."""

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30, read=120),
            follow_redirects=True,
            headers={"User-Agent": f"cell-ledger/{__version__}"},
        ) as http:
            key = cfg.ncbi_api_key.get_secret_value() if cfg.ncbi_api_key else None
            app.state.settings = cfg
            app.state.geo = GeoClient(http, api_key=key)
            app.state.sessions = SessionService(
                cfg.data_dir,
                http,
                store if store is not None else _store(cfg, http),
                max_concurrent=cfg.max_concurrent_downloads,
            )
            app.state.runs = RunService(
                app.state.sessions,
                max_concurrent=cfg.max_concurrent_runs,
                n_cpus=cfg.run_n_cpus,
                timeout_minutes=cfg.run_timeout_minutes,
                command=run_command,
            )
            removed = await app.state.sessions.sweep(timedelta(hours=cfg.session_ttl_hours))
            if removed:
                log.info("swept %d expired sessions", len(removed))
            # Nothing survives a restart in flight: say so on disk rather than hang forever.
            interrupted = app.state.sessions.recover() + app.state.runs.recover()
            if interrupted:
                log.warning("%d collect/run jobs were interrupted by the restart", interrupted)
            yield

    app = FastAPI(title="cell-ledger", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cfg.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(SessionNotFound)
    async def _session_not_found(request: Request, exc: SessionNotFound) -> JSONResponse:
        return JSONResponse({"detail": "session not found"}, status_code=404)

    for r in (health.router, geo.router, sessions.router, runs.router):
        app.include_router(r, prefix="/api")

    if cfg.web_dist is not None:
        if not (cfg.web_dist / "index.html").is_file():
            raise RuntimeError(
                f"CELL_LEDGER_WEB_DIST={cfg.web_dist} has no index.html; run `mise run build:web`"
            )
        # Not app.mount(): see spa.py for why the mount must refuse /api itself.
        app.router.routes.append(SpaMount(SpaStaticFiles(cfg.web_dist)))
    return app


app = create_app()

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import timedelta

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from cell_ledger.geo import GeoClient
from cell_ledger_api import __version__
from cell_ledger_api.discovery import ExaSearcher
from cell_ledger_api.routes import geo, health, sessions
from cell_ledger_api.sessions import SessionNotFound, SessionService
from cell_ledger_api.settings import Settings, settings
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
    exa: ExaSearcher | None = None,
) -> FastAPI:
    """``transport``, ``store`` and ``exa`` let tests swap out GEO, Supabase and Exa."""

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
            removed = await app.state.sessions.sweep(timedelta(hours=cfg.session_ttl_hours))
            if removed:
                log.info("swept %d expired sessions", len(removed))
            own_exa = None
            if exa is None and cfg.exa_api_key:
                from exa_py import AsyncExa

                own_exa = AsyncExa(api_key=cfg.exa_api_key.get_secret_value())
            app.state.exa = exa if exa is not None else own_exa
            try:
                yield
            finally:
                if own_exa is not None:
                    await own_exa.aclose()

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

    for r in (health.router, geo.router, sessions.router):
        app.include_router(r, prefix="/api")
    return app


app = create_app()

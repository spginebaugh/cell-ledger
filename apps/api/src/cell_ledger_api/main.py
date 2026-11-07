import asyncio
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
from cell_ledger_api.agent.design import Designer
from cell_ledger_api.agent.discover import Discoverer
from cell_ledger_api.agent.llm import TurnRunner, sdk_turn_runner
from cell_ledger_api.compare import CompareService
from cell_ledger_api.db import Database
from cell_ledger_api.discovery import ExaSearcher
from cell_ledger_api.pipeline import Pipeline
from cell_ledger_api.routes import agent, comparisons, geo, health, runs, sessions
from cell_ledger_api.runs import DEFAULT_COMMAND, RunService
from cell_ledger_api.sessions import SessionNotFound, SessionService
from cell_ledger_api.settings import Settings
from cell_ledger_api.spa import SpaMount, SpaStaticFiles
from cell_ledger_api.storage import SupabaseStore

log = logging.getLogger("cell_ledger_api")


def create_app(
    cfg: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    run_command: Sequence[str] = DEFAULT_COMMAND,
    compare_command: Sequence[str] = DEFAULT_COMMAND,
    exa: ExaSearcher | None = None,
    turn: TurnRunner | None = None,
) -> FastAPI:
    """``transport`` swaps out NCBI GEO, ``run_command`` the pipeline subprocess,
    ``compare_command`` the comparison subprocess, ``exa`` the web search and ``turn`` the
    calls to Claude. Postgres and
    Storage are never faked: tests run against the local Supabase stack, which applies the
    same migrations and bucket as the cloud project."""
    cfg = cfg if cfg is not None else Settings()  # type: ignore[call-arg]
    settings = cfg

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        db = await Database.connect(settings.database_url.get_secret_value())
        store = SupabaseStore(
            settings.supabase_url,
            settings.supabase_secret_key.get_secret_value(),
            settings.supabase_bucket,
        )
        await store.check()
        async with httpx.AsyncClient(
            transport=transport,
            timeout=httpx.Timeout(30, read=120),
            follow_redirects=True,
            headers={"User-Agent": f"cell-ledger/{__version__}"},
        ) as http:
            key = settings.ncbi_api_key.get_secret_value() if settings.ncbi_api_key else None
            app.state.settings = settings
            app.state.db = db
            app.state.geo = GeoClient(http, api_key=key)
            app.state.sessions = SessionService(
                db,
                store,
                settings.data_dir,
                http,
                max_concurrent=settings.max_concurrent_downloads,
                max_attempts=settings.max_attempts,
            )
            app.state.runs = RunService(
                app.state.sessions,
                max_concurrent=settings.max_concurrent_runs,
                n_cpus=settings.run_n_cpus,
                timeout_minutes=settings.run_timeout_minutes,
                command=run_command,
                max_attempts=settings.max_attempts,
            )
            app.state.comparisons = CompareService(
                app.state.sessions,
                app.state.runs,
                timeout_minutes=settings.compare_timeout_minutes,
                command=compare_command,
            )
            ttl = timedelta(hours=settings.session_ttl_hours)
            removed = await app.state.sessions.sweep(ttl)
            if removed:
                log.info("swept %d expired sessions", len(removed))

            async def sweep_forever() -> None:
                while True:
                    await asyncio.sleep(settings.sweep_interval_minutes * 60)
                    try:
                        gone = await app.state.sessions.sweep(ttl)
                        if gone:
                            log.info("swept %d expired sessions", len(gone))
                    except Exception:  # keep sweeping; the next pass retries
                        log.exception("session sweep failed")

            sweeper = asyncio.create_task(sweep_forever())

            own_exa = None
            if exa is None and settings.exa_api_key:
                from exa_py import AsyncExa

                own_exa = AsyncExa(api_key=settings.exa_api_key.get_secret_value())
            app.state.exa = exa if exa is not None else own_exa

            own_anthropic = None
            runner = turn
            if runner is None and settings.anthropic_api_key:
                import anthropic

                own_anthropic = anthropic.AsyncAnthropic(
                    api_key=settings.anthropic_api_key.get_secret_value(), max_retries=2
                )
                runner = sdk_turn_runner(own_anthropic)
            app.state.discoverer = Discoverer(
                app.state.geo,
                turn=runner,
                exa=app.state.exa,  # type: ignore[arg-type]
                model=settings.anthropic_model,
                effort=settings.anthropic_effort,
            )
            app.state.designer = Designer(
                turn=runner,
                model=settings.design_model or settings.anthropic_model,
                effort=settings.design_effort or settings.anthropic_effort,
            )
            app.state.pipeline = Pipeline(
                app.state.sessions, app.state.runs, app.state.comparisons, app.state.designer
            )
            # Recovery after the hooks are wired, so a re-dispatched download or run flows on.
            # Comparisons first: that step fails whatever is 'running', which at boot can only
            # be stale, and must not catch a comparison the run recovery's hook starts.
            await app.state.comparisons.recover()
            resumed = await app.state.sessions.recover() + await app.state.runs.recover()
            resumed += await app.state.pipeline.recover()
            if resumed:
                log.warning("re-dispatched %d jobs interrupted by the restart", resumed)
            try:
                yield
            finally:
                sweeper.cancel()
                if own_anthropic is not None:
                    await own_anthropic.close()
                if own_exa is not None:
                    await own_exa.aclose()
                await store.aclose()
                await db.close()

    app = FastAPI(title="cell-ledger", version=__version__, lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.exception_handler(SessionNotFound)
    async def _session_not_found(request: Request, exc: SessionNotFound) -> JSONResponse:
        return JSONResponse({"detail": "session not found"}, status_code=404)

    @app.exception_handler(httpx.HTTPError)
    async def _storage_error(request: Request, exc: httpx.HTTPError) -> JSONResponse:
        log.warning("storage request failed: %s", exc)
        return JSONResponse({"detail": f"storage unavailable: {exc}"}, status_code=502)

    for r in (
        health.router,
        geo.router,
        sessions.router,
        runs.router,
        comparisons.router,
        agent.router,
        agent.types_router,
    ):
        app.include_router(r, prefix="/api")

    if settings.web_dist is not None:
        if not (settings.web_dist / "index.html").is_file():
            raise RuntimeError(
                f"CELL_LEDGER_WEB_DIST={settings.web_dist} has no index.html; "
                "run `mise run build:web`"
            )
        # Not app.mount(): see spa.py for why the mount must refuse /api itself.
        app.router.routes.append(SpaMount(SpaStaticFiles(settings.web_dist)))
    return app


# uvicorn entry point (factory mode): `uvicorn --factory cell_ledger_api.main:create_app`.
# Settings come from CELL_LEDGER_* and .env; missing database or storage settings fail
# there, before anything listens. No module-level app, so importing this module reads no .env.

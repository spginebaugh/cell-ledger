from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from cell_ledger_api import __version__
from cell_ledger_api.routes import health
from cell_ledger_api.settings import settings


def create_app() -> FastAPI:
    app = FastAPI(title="cell-ledger", version=__version__)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(health.router, prefix="/api")
    return app


app = create_app()

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from cell_ledger import __version__ as core_version
from cell_ledger_api import __version__ as api_version

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    api_version: str
    core_version: str
    database: str


@router.get("/health", operation_id="getHealth")
async def get_health(request: Request) -> Health:
    """200 only when the API can reach Postgres; Fly and Docker health checks hit this."""
    try:
        await request.app.state.db.ping()
    except Exception as e:  # asyncpg raises many types; any of them means unhealthy
        raise HTTPException(503, f"database unreachable: {type(e).__name__}") from e
    return Health(status="ok", api_version=api_version, core_version=core_version, database="ok")

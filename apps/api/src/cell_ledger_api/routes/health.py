from fastapi import APIRouter
from pydantic import BaseModel

from cell_ledger import __version__ as core_version
from cell_ledger_api import __version__ as api_version

router = APIRouter(tags=["health"])


class Health(BaseModel):
    status: str
    api_version: str
    core_version: str


@router.get("/health", operation_id="getHealth")
def get_health() -> Health:
    return Health(status="ok", api_version=api_version, core_version=core_version)

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from cell_ledger.geo import DatasetRecord
from cell_ledger_api.sessions import SESSION_ID, CollectedDataset, SessionInfo, SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])

SessionId = Annotated[str, Path(pattern=SESSION_ID)]
Gse = Annotated[str, Path(pattern=r"^GSE\d+$")]
FileName = Annotated[str, Path(pattern=r"^[A-Za-z0-9._-]+$")]


class CollectRequest(BaseModel):
    gses: Annotated[list[Annotated[str, Field(pattern=r"^GSE\d+$")]], Field(min_length=1)]


class CollectResponse(BaseModel):
    datasets: list[CollectedDataset]


class FileUrl(BaseModel):
    url: str
    expires_in: int


def _service(request: Request) -> SessionService:
    return request.app.state.sessions


@router.post("", operation_id="createSession", status_code=201)
def create_session(request: Request) -> SessionInfo:
    return _service(request).create()


@router.post("/{session_id}/datasets", operation_id="collectDatasets")
async def collect_datasets(
    session_id: SessionId, body: CollectRequest, request: Request
) -> CollectResponse:
    """Download the given series into the session; each comes back ready or excluded."""
    limit = request.app.state.settings.max_datasets_per_request
    if len(body.gses) > limit:
        raise HTTPException(422, f"at most {limit} datasets per request")
    return CollectResponse(datasets=await _service(request).collect(session_id, body.gses))


@router.get("/{session_id}/datasets", operation_id="listDatasets")
def list_datasets(session_id: SessionId, request: Request) -> list[DatasetRecord]:
    return _service(request).datasets(session_id)


@router.get("/{session_id}/datasets/{gse}/files/{name}", operation_id="getDatasetFileUrl")
async def get_file_url(
    session_id: SessionId, gse: Gse, name: FileName, request: Request
) -> FileUrl:
    """Short-lived download link for one stored file."""
    expires_in = 600
    url = await _service(request).file_url(session_id, gse, name, expires_in)
    if url is None:
        raise HTTPException(404, "file not found in storage")
    return FileUrl(url=url, expires_in=expires_in)


@router.delete("/{session_id}", operation_id="deleteSession", status_code=204)
async def delete_session(session_id: SessionId, request: Request) -> None:
    await _service(request).delete(session_id)

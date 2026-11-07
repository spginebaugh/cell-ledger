from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request
from pydantic import BaseModel, Field

from cell_ledger_api.sessions import SESSION_ID, DatasetStatus, SessionInfo, SessionService

router = APIRouter(prefix="/sessions", tags=["sessions"])

SessionId = Annotated[str, Path(pattern=SESSION_ID)]
Gse = Annotated[str, Path(pattern=r"^GSE\d+$")]
# Relative paths inside a dataset or run folder, e.g. "dataset.json" or "figures/pca.png".
FileName = Annotated[str, Path(pattern=r"^[A-Za-z0-9._-]+(/[A-Za-z0-9._-]+)*$")]
SIGNED_URL_TTL = 600


class CollectRequest(BaseModel):
    gses: Annotated[list[Annotated[str, Field(pattern=r"^GSE\d+$")]], Field(min_length=1)]


class FileUrl(BaseModel):
    url: str
    expires_in: int


def service(request: Request) -> SessionService:
    return request.app.state.sessions


async def signed(request: Request, session_id: str, rel: str) -> FileUrl:
    url = await service(request).file_url(session_id, rel, SIGNED_URL_TTL)
    if url is None:
        raise HTTPException(404, "file not found in storage")
    return FileUrl(url=url, expires_in=SIGNED_URL_TTL)


@router.post("", operation_id="createSession", status_code=201)
async def create_session(request: Request) -> SessionInfo:
    return await service(request).create()


@router.get("/{session_id}", operation_id="getSession")
async def get_session(session_id: SessionId, request: Request) -> SessionInfo:
    return await service(request).get(session_id)


@router.post("/{session_id}/datasets", operation_id="collectDatasets", status_code=202)
async def collect_datasets(
    session_id: SessionId, body: CollectRequest, request: Request
) -> list[DatasetStatus]:
    """Start downloading the given series in the background.

    Returns at once with every dataset in the session; poll ``listDatasets`` until the ones
    you asked for are no longer ``pending``. Each arrives ready, excluded or failed.
    """
    limit = request.app.state.settings.max_datasets_per_request
    if len(body.gses) > limit:
        raise HTTPException(422, f"at most {limit} datasets per request")
    return await service(request).collect(session_id, body.gses)


@router.get("/{session_id}/datasets", operation_id="listDatasets")
async def list_datasets(session_id: SessionId, request: Request) -> list[DatasetStatus]:
    """Every dataset in the session with its current status."""
    return await service(request).datasets(session_id)


@router.get("/{session_id}/datasets/{gse}/files/{name:path}", operation_id="getDatasetFileUrl")
async def get_dataset_file_url(
    session_id: SessionId, gse: Gse, name: FileName, request: Request
) -> FileUrl:
    """Short-lived download link for one stored file."""
    return await signed(request, session_id, f"geo/{gse}/{name}")


@router.delete("/{session_id}", operation_id="deleteSession", status_code=204)
async def delete_session(session_id: SessionId, request: Request) -> None:
    await service(request).delete(session_id)

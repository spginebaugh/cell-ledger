from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request

from cell_ledger_api.routes.sessions import FileName, FileUrl, Gse, SessionId, signed
from cell_ledger_api.runs import CountsMissing, RunConflict, RunRequest, RunService, RunStatus

router = APIRouter(prefix="/sessions/{session_id}/runs", tags=["runs"])

ContrastName = Annotated[str, Path(pattern=r"^[A-Za-z0-9._-]+$")]


def service(request: Request) -> RunService:
    return request.app.state.runs


@router.post("", operation_id="startRun", status_code=202)
async def start_run(session_id: SessionId, body: RunRequest, request: Request) -> list[RunStatus]:
    """Run the pipeline on a collected dataset in the background, one entry per contrast.

    Poll ``listRuns`` until the status leaves ``running``. The counts must already be in
    the session (``collectDatasets``) and the dataset must be ``ready``.
    """
    try:
        return await service(request).start(session_id, body)
    except CountsMissing as e:
        raise HTTPException(409, str(e)) from e
    except RunConflict as e:
        raise HTTPException(409, str(e)) from e


@router.get("", operation_id="listRuns")
async def list_runs(session_id: SessionId, request: Request) -> list[RunStatus]:
    return await service(request).statuses(session_id)


@router.get("/{gse}/{contrast}/files/{name:path}", operation_id="getRunFileUrl")
async def get_run_file_url(
    session_id: SessionId, gse: Gse, contrast: ContrastName, name: FileName, request: Request
) -> FileUrl:
    """Short-lived download link for one run output, e.g. ``report.json`` or ``figures/pca.png``."""
    return await signed(request, session_id, f"runs/{gse}/{contrast}/{name}")

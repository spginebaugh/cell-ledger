from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, Request

from cell_ledger_api.compare import (
    CompareRequest,
    CompareService,
    ComparisonConflict,
    ComparisonNotFound,
    ComparisonStatus,
    ComparisonView,
    MembersNotReady,
)
from cell_ledger_api.routes.sessions import VIEW_URL_TTL, FileName, FileUrl, SessionId, signed

router = APIRouter(prefix="/sessions/{session_id}/comparisons", tags=["comparisons"])

ComparisonName = Annotated[str, Path(pattern=r"^[a-z0-9]+(_[a-z0-9]+)*$")]


def service(request: Request) -> CompareService:
    return request.app.state.comparisons


@router.post("", operation_id="startComparison", status_code=202)
async def start_comparison(
    session_id: SessionId, body: CompareRequest, request: Request
) -> ComparisonStatus:
    """Compare finished runs in this session in the background.

    Every member must be a run of this session that is no longer running; the comparison
    itself decides which members it can pool and records the rest as excluded. Poll
    ``listComparisons`` or ``getComparison`` until the status leaves ``running``.
    """
    try:
        return await service(request).start(session_id, body)
    except MembersNotReady as e:
        raise HTTPException(409, str(e)) from e
    except ComparisonConflict as e:
        raise HTTPException(409, str(e)) from e


@router.get("", operation_id="listComparisons")
async def list_comparisons(session_id: SessionId, request: Request) -> list[ComparisonStatus]:
    return await service(request).statuses(session_id)


@router.get("/{name}", operation_id="getComparison")
async def get_comparison(
    session_id: SessionId, name: ComparisonName, request: Request
) -> ComparisonView:
    """The comparison page in one call: status, report and signed URLs for its files."""
    try:
        return await service(request).view(session_id, name, url_ttl=VIEW_URL_TTL)
    except ComparisonNotFound as e:
        raise HTTPException(404, f"no comparison named {e}") from e


@router.get("/{name}/files/{file:path}", operation_id="getComparisonFileUrl")
async def get_comparison_file_url(
    session_id: SessionId, name: ComparisonName, file: FileName, request: Request
) -> FileUrl:
    return await signed(request, session_id, f"comparisons/{name}/{file}")

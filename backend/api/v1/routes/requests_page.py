from fastapi import APIRouter, Depends, HTTPException, Query
from typing import Optional

from api.v1.schemas.requests_page import (
    ActiveCountResponse,
    ActiveRequestsResponse,
    ApprovalActionResponse,
    CancelRequestResponse,
    ClearHistoryResponse,
    RequestHistoryResponse,
    RetryRequestResponse,
)
from core.dependencies import get_requests_page_service
from core.dependencies.type_aliases import CurrentUserDep, CurrentAdminDep
from infrastructure.validators import validate_mbid
from infrastructure.msgspec_fastapi import MsgSpecRoute
from services.requests_page_service import RequestsPageService

router = APIRouter(route_class=MsgSpecRoute, prefix="/requests", tags=["requests-page"])


@router.get("/active", response_model=ActiveRequestsResponse)
async def get_active_requests(
    service: RequestsPageService = Depends(get_requests_page_service),
    current_user: CurrentUserDep = None,
):
    user_id = None if current_user.role == "admin" else current_user.id
    return await service.get_active_requests(user_id=user_id)


@router.get("/active/count", response_model=ActiveCountResponse)
async def get_active_request_count(
    service: RequestsPageService = Depends(get_requests_page_service),
    current_user: CurrentUserDep = None,
):
    user_id = None if current_user.role == "admin" else current_user.id
    count = await service.get_active_count(user_id=user_id)
    return ActiveCountResponse(count=count)


@router.get("/history", response_model=RequestHistoryResponse)
async def get_request_history(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    sort: Optional[str] = Query(None, pattern="^(newest|oldest|status)$"),
    service: RequestsPageService = Depends(get_requests_page_service),
    current_user: CurrentUserDep = None,
):
    user_id = None if current_user.role == "admin" else current_user.id
    return await service.get_request_history(
        page=page, page_size=page_size, status_filter=status, sort=sort, user_id=user_id
    )


@router.delete("/active/{musicbrainz_id}", response_model=CancelRequestResponse)
async def cancel_request(
    musicbrainz_id: str,
    service: RequestsPageService = Depends(get_requests_page_service),
    current_user: CurrentUserDep = None,
):
    try:
        musicbrainz_id = validate_mbid(musicbrainz_id, "album")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid MBID format")
    user_id = None if current_user.role == "admin" else current_user.id
    return await service.cancel_request(musicbrainz_id, user_id=user_id)


@router.post("/retry/{musicbrainz_id}", response_model=RetryRequestResponse)
async def retry_request(
    musicbrainz_id: str,
    service: RequestsPageService = Depends(get_requests_page_service),
    current_user: CurrentUserDep = None,
):
    try:
        musicbrainz_id = validate_mbid(musicbrainz_id, "album")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid MBID format")
    user_id = None if current_user.role == "admin" else current_user.id
    return await service.retry_request(musicbrainz_id, user_id=user_id)


@router.delete("/history/{musicbrainz_id}", response_model=ClearHistoryResponse)
async def clear_history_item(
    musicbrainz_id: str,
    service: RequestsPageService = Depends(get_requests_page_service),
    current_user: CurrentUserDep = None,
):
    try:
        musicbrainz_id = validate_mbid(musicbrainz_id, "album")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid MBID format")
    user_id = None if current_user.role == "admin" else current_user.id
    deleted = await service.clear_history_item(musicbrainz_id, user_id=user_id)
    return ClearHistoryResponse(success=deleted)


@router.get("/pending-approvals", response_model=ActiveRequestsResponse)
async def get_pending_approvals(
    service: RequestsPageService = Depends(get_requests_page_service),
    _admin: CurrentAdminDep = None,
):
    return await service.get_pending_approvals()


@router.post("/approve/{musicbrainz_id}", response_model=ApprovalActionResponse)
async def approve_request(
    musicbrainz_id: str,
    service: RequestsPageService = Depends(get_requests_page_service),
    _admin: CurrentAdminDep = None,
):
    try:
        musicbrainz_id = validate_mbid(musicbrainz_id, "album")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid MBID format")
    result = await service.approve_request(musicbrainz_id)
    return ApprovalActionResponse(success=result.success, message=result.message)


@router.post("/reject/{musicbrainz_id}", response_model=ApprovalActionResponse)
async def reject_request(
    musicbrainz_id: str,
    service: RequestsPageService = Depends(get_requests_page_service),
    _admin: CurrentAdminDep = None,
):
    try:
        musicbrainz_id = validate_mbid(musicbrainz_id, "album")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid MBID format")
    result = await service.reject_request(musicbrainz_id)
    return ApprovalActionResponse(success=result.success, message=result.message)

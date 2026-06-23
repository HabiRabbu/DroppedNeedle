import logging
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query

from api.v1.schemas.local_files import (
    CrateResponse,
    DecadesResponse,
    LocalAlbumMatch,
    LocalAlbumSummary,
    LocalPaginatedResponse,
    LocalSearchResponse,
    LocalStorageStats,
    LocalTrackInfo,
)
from core.dependencies import get_local_files_service
from core.exceptions import ExternalServiceError
from infrastructure.msgspec_fastapi import MsgSpecRoute
from services.local_files_service import LocalFilesService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/local", tags=["local-files"])


@router.get("/albums", response_model=LocalPaginatedResponse)
async def get_local_albums(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: Literal["name", "date_added", "year", "random", "rediscover"] = "name",
    sort_order: Literal["asc", "desc"] = Query(default="asc"),
    q: str | None = Query(default=None, min_length=1),
    decade: int | None = Query(default=None),
    service: LocalFilesService = Depends(get_local_files_service),
) -> LocalPaginatedResponse:
    try:
        return await service.get_albums(
            limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order,
            search_query=q, decade=decade,
        )
    except ExternalServiceError as e:
        logger.error("Failed to get local albums: %s", e)
        raise HTTPException(status_code=502, detail="Failed to get local albums")


@router.get("/albums/match/{musicbrainz_id}", response_model=LocalAlbumMatch)
async def match_local_album(
    musicbrainz_id: str,
    service: LocalFilesService = Depends(get_local_files_service),
) -> LocalAlbumMatch:
    try:
        return await service.match_album_by_mbid(musicbrainz_id)
    except ExternalServiceError as e:
        logger.error("Failed to match local album %s: %s", musicbrainz_id, e)
        raise HTTPException(status_code=502, detail="Failed to match local album")


@router.get(
    "/albums/{mbid}/tracks", response_model=list[LocalTrackInfo]
)
async def get_local_album_tracks(
    mbid: str,
    service: LocalFilesService = Depends(get_local_files_service),
) -> list[LocalTrackInfo]:
    try:
        return await service.get_album_tracks_by_id(mbid)
    except ExternalServiceError as e:
        logger.error("Failed to get local album tracks %s: %s", mbid, e)
        raise HTTPException(
            status_code=502, detail="Failed to get local album tracks"
        )


@router.get("/search", response_model=LocalSearchResponse)
async def search_local(
    q: str = Query(min_length=1),
    service: LocalFilesService = Depends(get_local_files_service),
) -> LocalSearchResponse:
    try:
        return await service.search(q)
    except ExternalServiceError as e:
        logger.error("Failed to search local files: %s", e)
        raise HTTPException(
            status_code=502, detail="Failed to search local files"
        )


@router.get("/recent", response_model=list[LocalAlbumSummary])
async def get_local_recent(
    limit: int = Query(default=20, ge=1, le=50),
    service: LocalFilesService = Depends(get_local_files_service),
) -> list[LocalAlbumSummary]:
    try:
        return await service.get_recently_added(limit=limit)
    except ExternalServiceError as e:
        logger.error("Failed to get recent local albums: %s", e)
        raise HTTPException(
            status_code=502, detail="Failed to get recent local albums"
        )


@router.get("/stats", response_model=LocalStorageStats)
async def get_local_stats(
    service: LocalFilesService = Depends(get_local_files_service),
) -> LocalStorageStats:
    return await service.get_storage_stats()


@router.get("/suggestions", response_model=CrateResponse)
async def get_local_suggestions(
    limit: int = Query(default=12, ge=1, le=40),
    decade: int | None = Query(default=None),
    service: LocalFilesService = Depends(get_local_files_service),
) -> CrateResponse:
    try:
        items = await service.get_crate_suggestions(limit=limit, decade=decade)
        return CrateResponse(items=items)
    except ExternalServiceError as e:
        logger.error("Failed to get crate suggestions: %s", e)
        raise HTTPException(status_code=502, detail="Failed to get suggestions")


@router.get("/decades", response_model=DecadesResponse)
async def get_local_decades(
    service: LocalFilesService = Depends(get_local_files_service),
) -> DecadesResponse:
    try:
        return DecadesResponse(items=await service.get_decades())
    except ExternalServiceError as e:
        logger.error("Failed to get decades: %s", e)
        raise HTTPException(status_code=502, detail="Failed to get decades")

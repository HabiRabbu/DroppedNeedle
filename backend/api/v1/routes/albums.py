import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from core.exceptions import ClientDisconnectedError
from api.v1.schemas.album import AlbumInfo, AlbumBasicInfo, AlbumTracksInfo, LastFmAlbumEnrichment
from api.v1.schemas.discovery import SimilarAlbumsResponse, MoreByArtistResponse
from core.dependencies import get_album_service, get_album_discovery_service, get_album_enrichment_service, get_navidrome_library_service
from services.album_service import AlbumService
from services.album_discovery_service import AlbumDiscoveryService
from services.album_enrichment_service import AlbumEnrichmentService
from services.navidrome_library_service import NavidromeLibraryService
from middleware import CurrentUserDep
from infrastructure.validators import is_unknown_mbid
from infrastructure.queue.priority_queue import RequestPriority
from infrastructure.degradation import try_get_degradation_context
from infrastructure.msgspec_fastapi import MsgSpecRoute

import msgspec.structs
import msgspec

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/albums", tags=["album"])


@router.get("/{album_id}", response_model=AlbumInfo)
async def get_album(
    album_id: str,
    album_service: AlbumService = Depends(get_album_service)
):
    if is_unknown_mbid(album_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unknown album ID: {album_id}"
        )
    
    try:
        result = await album_service.get_album_info(album_id)
        ctx = try_get_degradation_context()
        if ctx is not None and ctx.has_degradation():
            result = msgspec.structs.replace(result, service_status=ctx.degraded_summary())
        return result
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid album request"
        )


@router.post("/{album_id}/refresh", response_model=AlbumBasicInfo)
async def refresh_album(
    album_id: str,
    album_service: AlbumService = Depends(get_album_service),
    navidrome_service: NavidromeLibraryService = Depends(get_navidrome_library_service),
):
    if is_unknown_mbid(album_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unknown album ID: {album_id}"
        )

    try:
        navidrome_service.invalidate_album_cache(album_id)
        await album_service.refresh_album(album_id)
        return await album_service.get_album_basic_info(album_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid album request"
        )


@router.get("/{album_id}/basic", response_model=AlbumBasicInfo)
async def get_album_basic(
    album_id: str,
    request: Request,
    background_tasks: BackgroundTasks,
    album_service: AlbumService = Depends(get_album_service)
):
    if await request.is_disconnected():
        raise ClientDisconnectedError("Client disconnected")
    
    if is_unknown_mbid(album_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unknown album ID: {album_id}"
        )
    
    try:
        result = await album_service.get_album_basic_info(album_id)
        background_tasks.add_task(album_service.warm_full_album_cache, album_id)
        return result
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid album request"
        )


@router.get("/{album_id}/tracks", response_model=AlbumTracksInfo)
async def get_album_tracks(
    album_id: str,
    request: Request,
    album_service: AlbumService = Depends(get_album_service)
):
    if await request.is_disconnected():
        raise ClientDisconnectedError("Client disconnected")
    
    if is_unknown_mbid(album_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unknown album ID: {album_id}"
        )
    
    try:
        return await album_service.get_album_tracks_info(album_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid album request"
        )


@router.get("/{album_id}/similar", response_model=SimilarAlbumsResponse)
async def get_similar_albums(
    album_id: str,
    current_user: CurrentUserDep,
    artist_id: str = Query(..., description="Artist MBID for similarity lookup"),
    count: int = Query(default=10, ge=1, le=30),
    discovery_service: AlbumDiscoveryService = Depends(get_album_discovery_service)
):
    if is_unknown_mbid(album_id) or is_unknown_mbid(artist_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or unknown album/artist ID"
        )
    return await discovery_service.get_similar_albums(album_id, artist_id, count, user_id=current_user.id)


@router.get("/{album_id}/more-by-artist", response_model=MoreByArtistResponse)
async def get_more_by_artist(
    album_id: str,
    artist_id: str = Query(..., description="Artist MBID"),
    count: int = Query(default=10, ge=1, le=30),
    discovery_service: AlbumDiscoveryService = Depends(get_album_discovery_service)
):
    if is_unknown_mbid(artist_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or unknown artist ID"
        )
    return await discovery_service.get_more_by_artist(
        artist_id, album_id, count, priority=RequestPriority.USER_INITIATED
    )


@router.get("/{album_id}/lastfm", response_model=LastFmAlbumEnrichment)
async def get_album_lastfm_enrichment(
    album_id: str,
    artist_name: str = Query(..., description="Artist name for Last.fm lookup"),
    album_name: str = Query(..., description="Album name for Last.fm lookup"),
    enrichment_service: AlbumEnrichmentService = Depends(get_album_enrichment_service),
):
    if is_unknown_mbid(album_id):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid or unknown album ID: {album_id}"
        )
    result = await enrichment_service.get_lastfm_enrichment(
        artist_name=artist_name, album_name=album_name, album_mbid=album_id
    )
    if result is None:
        return LastFmAlbumEnrichment()
    return result

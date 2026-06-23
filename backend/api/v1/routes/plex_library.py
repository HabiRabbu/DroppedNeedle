import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response

from api.v1.schemas.plex import (
    PlexAlbumDetail,
    PlexAlbumMatch,
    PlexAlbumPage,
    PlexAlbumSummary,
    PlexAnalyticsResponse,
    PlexArtistIndexResponse,
    PlexArtistPage,
    PlexArtistSummary,
    PlexDiscoveryResponse,
    PlexHistoryResponse,
    PlexHubResponse,
    PlexImportResult,
    PlexLibraryStats,
    PlexPlaylistDetail,
    PlexPlaylistSummary,
    PlexSearchResponse,
    PlexSessionsResponse,
    PlexTrackPage,
)
from core.dependencies import (
    CurrentUserDep,
    get_jellyfin_library_service,
    get_local_files_service,
    get_navidrome_library_service,
    get_plex_library_service,
    get_plex_repository,
    get_playlist_service,
)
from core.exceptions import ExternalServiceError, ResourceNotFoundError
from infrastructure.msgspec_fastapi import MsgSpecRoute
from repositories.plex_repository import PlexRepository
from services.plex_library_service import PlexLibraryService
from services.playlist_service import PlaylistService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/plex", tags=["plex-library"])

_PLEX_SORT_FIELD: dict[str, str] = {
    "name": "titleSort",
    "date_added": "addedAt",
    "year": "year",
    "play_count": "viewCount",
    "rating": "userRating",
    "last_played": "lastViewedAt",
}


@router.get("/hub", response_model=PlexHubResponse)
async def get_plex_hub(
    current_user: CurrentUserDep,
    service: PlexLibraryService = Depends(get_plex_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
) -> PlexHubResponse:
    try:
        hub = await service.get_hub_data()
        imported_ids = await playlist_service.get_imported_source_ids("plex:", user_id=current_user.id)
        for p in hub.playlists:
            if p.id in imported_ids:
                p.is_imported = True
        return hub
    except ExternalServiceError as e:
        logger.error("Plex service error getting hub data: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/albums", response_model=PlexAlbumPage)
async def get_plex_albums(
    limit: int = Query(default=48, ge=1, le=500, alias="limit"),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="name"),
    sort_order: str = Query(default=""),
    genre: str = Query(default=""),
    mood: str = Query(default=""),
    decade: str = Query(default=""),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexAlbumPage:
    field = _PLEX_SORT_FIELD.get(sort_by, "titleSort")
    direction = "desc" if sort_order == "desc" else "asc"
    plex_sort = f"{field}:{direction}"
    try:
        items, total_from_plex = await service.get_albums(
            size=limit, offset=offset, sort=plex_sort,
            genre=genre if genre else None,
            mood=mood if mood else None,
            decade=decade if decade else None,
        )
    except ExternalServiceError as e:
        logger.error("Plex service error getting albums: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")

    return PlexAlbumPage(items=items, total=total_from_plex)


@router.get("/albums/{rating_key}", response_model=PlexAlbumDetail)
async def get_plex_album_detail(
    rating_key: str,
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexAlbumDetail:
    result = await service.get_album_detail(rating_key)
    if not result:
        raise HTTPException(status_code=404, detail="Album not found")
    return result


@router.get("/artists/browse", response_model=PlexArtistPage)
async def browse_plex_artists(
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("titleSort:asc"),
    search: str = Query(""),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexArtistPage:
    try:
        items, total = await service.browse_artists(size=limit, offset=offset, sort=sort, search=search)
        return PlexArtistPage(items=items, total=total, offset=offset, limit=limit)
    except ExternalServiceError as e:
        logger.error("Plex service error browsing artists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/artists", response_model=list[PlexArtistSummary])
async def get_plex_artists(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> list[PlexArtistSummary]:
    try:
        return await service.get_artists()
    except ExternalServiceError as e:
        logger.error("Plex service error getting artists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/artists/index", response_model=PlexArtistIndexResponse)
async def get_plex_artists_index(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexArtistIndexResponse:
    try:
        return await service.get_artists_index()
    except ExternalServiceError as e:
        logger.error("Plex service error getting artist index: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/tracks", response_model=PlexTrackPage)
async def browse_plex_tracks(
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort: str = Query("titleSort:asc"),
    search: str = Query(""),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexTrackPage:
    try:
        items, total = await service.browse_tracks(size=limit, offset=offset, sort=sort, search=search)
        return PlexTrackPage(items=items, total=total, offset=offset, limit=limit)
    except ExternalServiceError as e:
        logger.error("Plex service error browsing tracks: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/search", response_model=PlexSearchResponse)
async def search_plex(
    q: str = Query(..., min_length=1),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexSearchResponse:
    try:
        return await service.search(q)
    except ExternalServiceError as e:
        logger.error("Plex service error searching: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/recent", response_model=list[PlexAlbumSummary])
async def get_plex_recent(
    limit: int = Query(default=20, ge=1, le=50),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> list[PlexAlbumSummary]:
    try:
        return await service.get_recent(limit=limit)
    except ExternalServiceError as e:
        logger.error("Plex service error getting recent: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/recently-added", response_model=list[PlexAlbumSummary])
async def get_plex_recently_added(
    limit: int = Query(default=20, ge=1, le=50),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> list[PlexAlbumSummary]:
    try:
        return await service.get_recently_added_albums(limit=limit)
    except ExternalServiceError as e:
        logger.error("Plex service error getting recently added: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/genres", response_model=list[str])
async def get_plex_genres(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> list[str]:
    try:
        return await service.get_genres()
    except ExternalServiceError as e:
        logger.error("Plex service error getting genres: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/genres/songs", response_model=PlexTrackPage)
async def get_plex_genre_songs(
    genre: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexTrackPage:
    tracks, total = await service.get_songs_by_genre(genre, limit=limit, offset=offset)
    return PlexTrackPage(items=tracks, total=total, offset=offset, limit=limit)


@router.get("/moods", response_model=list[str])
async def get_plex_moods(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> list[str]:
    try:
        return await service.get_moods()
    except ExternalServiceError as e:
        logger.error("Plex service error getting moods: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/stats", response_model=PlexLibraryStats)
async def get_plex_stats(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexLibraryStats:
    try:
        return await service.get_stats()
    except ExternalServiceError as e:
        logger.error("Plex service error getting stats: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Plex")


@router.get("/discovery", response_model=PlexDiscoveryResponse)
async def get_plex_discovery(
    count: int = Query(default=10, ge=1, le=20),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexDiscoveryResponse:
    return await service.get_discovery_hubs(count=count)


@router.get("/thumb/{rating_key}")
async def get_plex_thumb(
    rating_key: str,
    size: int = Query(default=500, ge=32, le=1200),
    repo: PlexRepository = Depends(get_plex_repository),
) -> Response:
    try:
        image_bytes, content_type = await repo.proxy_thumb(rating_key, size)
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    except ExternalServiceError as e:
        logger.warning("Plex thumb failed for %s: %s", rating_key, e)
        raise HTTPException(status_code=502, detail="Failed to fetch thumbnail")


@router.get("/playlist-thumb/{rating_key}")
async def get_plex_playlist_thumb(
    rating_key: str,
    size: int = Query(default=500, ge=32, le=1200),
    repo: PlexRepository = Depends(get_plex_repository),
) -> Response:
    try:
        image_bytes, content_type = await repo.proxy_playlist_composite(rating_key, size)
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=86400"},
        )
    except ExternalServiceError as e:
        logger.warning("Plex playlist composite failed for %s: %s", rating_key, e)
        raise HTTPException(status_code=502, detail="Failed to fetch playlist thumbnail")


@router.get("/album-match/{album_id}", response_model=PlexAlbumMatch)
async def match_plex_album(
    album_id: str,
    name: str = Query(default=""),
    artist: str = Query(default=""),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexAlbumMatch:
    try:
        return await service.get_album_match(
            album_id=album_id, album_name=name, artist_name=artist,
        )
    except ExternalServiceError as e:
        logger.error("Failed to match Plex album %s: %s", album_id, e)
        raise HTTPException(status_code=502, detail="Failed to match Plex album")


@router.get("/playlists", response_model=list[PlexPlaylistSummary])
async def get_plex_playlists(
    current_user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=200),
    service: PlexLibraryService = Depends(get_plex_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
) -> list[PlexPlaylistSummary]:
    try:
        playlists = await service.list_playlists(limit=limit)
        imported_ids = await playlist_service.get_imported_source_ids("plex:", user_id=current_user.id)
        for p in playlists:
            if p.id in imported_ids:
                p.is_imported = True
        return playlists
    except ExternalServiceError as e:
        logger.error("Failed to get Plex playlists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to get Plex playlists")


@router.get("/playlists/{playlist_id}", response_model=PlexPlaylistDetail)
async def get_plex_playlist_detail(
    playlist_id: str,
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexPlaylistDetail:
    try:
        return await service.get_playlist_detail(playlist_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Plex playlist not found")
    except ExternalServiceError as e:
        logger.error("Failed to get Plex playlist %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to get Plex playlist")


@router.post("/playlists/{playlist_id}/import", response_model=PlexImportResult)
async def import_plex_playlist(
    playlist_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    service: PlexLibraryService = Depends(get_plex_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
    jf_service=Depends(get_jellyfin_library_service),
    local_service=Depends(get_local_files_service),
    nd_service=Depends(get_navidrome_library_service),
) -> PlexImportResult:
    try:
        result = await service.import_playlist(playlist_id, playlist_service, requesting=current_user)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Plex playlist not found")
    except ExternalServiceError as e:
        logger.error("Failed to import Plex playlist %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to import Plex playlist")

    if not result.already_imported:
        background_tasks.add_task(
            playlist_service.resolve_track_sources,
            result.droppedneedle_playlist_id,
            jf_service=jf_service,
            local_service=local_service,
            nd_service=nd_service,
            plex_service=service,
        )
    return result


@router.get("/sessions", response_model=PlexSessionsResponse)
async def get_plex_sessions(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexSessionsResponse:
    return await service.get_sessions()


@router.get("/history", response_model=PlexHistoryResponse)
async def get_plex_history(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexHistoryResponse:
    return await service.get_history(limit=limit, offset=offset)


@router.get("/analytics", response_model=PlexAnalyticsResponse)
async def get_plex_analytics(
    service: PlexLibraryService = Depends(get_plex_library_service),
) -> PlexAnalyticsResponse:
    return await service.get_analytics()

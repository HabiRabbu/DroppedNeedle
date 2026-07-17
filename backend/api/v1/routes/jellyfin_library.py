import logging
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import Response

from api.v1.schemas.jellyfin import (
    JellyfinAlbumDetail,
    JellyfinAlbumMatch,
    JellyfinAlbumSummary,
    JellyfinArtistIndexResponse,
    JellyfinArtistPage,
    JellyfinArtistSummary,
    JellyfinFavoritesExpanded,
    JellyfinFilterFacets,
    JellyfinHubResponse,
    JellyfinImportResult,
    JellyfinLibraryStats,
    JellyfinLyricsResponse,
    JellyfinPaginatedResponse,
    JellyfinPlaylistDetail,
    JellyfinPlaylistCollection,
    JellyfinSearchResponse,
    JellyfinSessionsResponse,
    JellyfinTrackInfo,
    JellyfinTrackPage,
)
from core.dependencies import (
    CurrentUserDep,
    get_jellyfin_library_service,
    get_jellyfin_repository,
    get_local_files_service,
    get_navidrome_library_service,
    get_plex_library_service,
    get_playlist_service,
)
from core.exceptions import ExternalServiceError, ResourceNotFoundError
from infrastructure.msgspec_fastapi import MsgSpecRoute
from repositories.jellyfin_repository import JellyfinRepository
from services.jellyfin_library_service import JellyfinLibraryService
from services.playlist_service import PlaylistService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/jellyfin", tags=["jellyfin-library"])


@router.get("/hub", response_model=JellyfinHubResponse)
async def get_jellyfin_hub(
    current_user: CurrentUserDep,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinHubResponse:
    try:
        return await service.get_hub_data()
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting hub data: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/image/{item_id}")
async def get_jellyfin_image(
    item_id: str,
    size: int = Query(default=500, ge=32, le=1200),
    repo: JellyfinRepository = Depends(get_jellyfin_repository),
) -> Response:
    try:
        image_bytes, content_type = await repo.proxy_image(item_id, size)
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    except ExternalServiceError as e:
        logger.warning("Jellyfin image failed for %s: %s", item_id, e)
        raise HTTPException(status_code=502, detail="Failed to fetch image")


@router.get("/playlist-image/{playlist_id}/{item_id}")
async def get_jellyfin_playlist_image(
    playlist_id: str,
    item_id: str,
    current_user: CurrentUserDep,
    size: int = Query(default=500, ge=32, le=1200),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> Response:
    try:
        image_bytes, content_type = await service.get_playlist_image(
            playlist_id, item_id, current_user, size
        )
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "private, no-store"},
        )
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Jellyfin playlist image not found")
    except ExternalServiceError as e:
        logger.warning("Jellyfin playlist image failed for %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to fetch image")


@router.get("/recently-added", response_model=list[JellyfinAlbumSummary])
async def get_jellyfin_recently_added(
    limit: int = Query(default=20, ge=1, le=50),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinAlbumSummary]:
    try:
        return await service.get_recently_added(limit=limit)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting recently added: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/most-played/artists", response_model=list[JellyfinArtistSummary])
async def get_jellyfin_most_played_artists(
    limit: int = Query(default=10, ge=1, le=50),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinArtistSummary]:
    try:
        return await service.get_most_played_artists(limit=limit)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting most played artists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/most-played/albums", response_model=list[JellyfinAlbumSummary])
async def get_jellyfin_most_played_albums(
    limit: int = Query(default=10, ge=1, le=50),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinAlbumSummary]:
    try:
        return await service.get_most_played_albums(limit=limit)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting most played albums: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/albums", response_model=JellyfinPaginatedResponse)
async def get_jellyfin_albums(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    sort_by: Literal["SortName", "DateCreated", "PlayCount", "ProductionYear"] = Query(default="SortName"),
    sort_order: Literal["Ascending", "Descending"] = Query(default="Ascending"),
    genre: str | None = Query(default=None),
    year: int | None = Query(default=None),
    tags: str | None = Query(default=None),
    studios: str | None = Query(default=None),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinPaginatedResponse:
    try:
        items, total = await service.get_albums(
            limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order,
            genre=genre, year=year, tags=tags, studios=studios,
        )
        return JellyfinPaginatedResponse(
            items=items, total=total, offset=offset, limit=limit
        )
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting albums: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/albums/{album_id}", response_model=JellyfinAlbumDetail)
async def get_jellyfin_album_detail(
    album_id: str,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinAlbumDetail:
    result = await service.get_album_detail(album_id)
    if not result:
        raise HTTPException(status_code=404, detail="Album not found")
    return result


@router.get(
    "/albums/{album_id}/tracks", response_model=list[JellyfinTrackInfo]
)
async def get_jellyfin_album_tracks(
    album_id: str,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinTrackInfo]:
    try:
        return await service.get_album_tracks(album_id)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting album tracks %s: %s", album_id, e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get(
    "/albums/match/{musicbrainz_id}", response_model=JellyfinAlbumMatch
)
async def match_jellyfin_album(
    musicbrainz_id: str,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinAlbumMatch:
    try:
        return await service.match_album_by_mbid(musicbrainz_id)
    except ExternalServiceError as e:
        logger.error("Failed to match Jellyfin album %s: %s", musicbrainz_id, e)
        raise HTTPException(status_code=502, detail="Failed to match Jellyfin album")


@router.get("/artists/browse", response_model=JellyfinArtistPage)
async def browse_jellyfin_artists(
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("SortName"),
    sort_order: str = Query("Ascending"),
    search: str = Query(""),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinArtistPage:
    try:
        items, total = await service.browse_artists(
            limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order, search=search
        )
        return JellyfinArtistPage(items=items, total=total, offset=offset, limit=limit)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error browsing artists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/artists", response_model=list[JellyfinArtistSummary])
async def get_jellyfin_artists(
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinArtistSummary]:
    return await service.get_artists(limit=limit, offset=offset)


@router.get("/artists/index", response_model=JellyfinArtistIndexResponse)
async def get_jellyfin_artists_index(
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinArtistIndexResponse:
    try:
        return await service.get_artists_index()
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting artist index: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/tracks", response_model=JellyfinTrackPage)
async def browse_jellyfin_tracks(
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    sort_by: str = Query("SortName"),
    sort_order: str = Query("Ascending"),
    search: str = Query(""),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinTrackPage:
    try:
        items, total = await service.browse_tracks(
            limit=limit, offset=offset, sort_by=sort_by, sort_order=sort_order, search=search
        )
        return JellyfinTrackPage(items=items, total=total, offset=offset, limit=limit)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error browsing tracks: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/search", response_model=JellyfinSearchResponse)
async def search_jellyfin(
    q: str = Query(..., min_length=1),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinSearchResponse:
    return await service.search(q)


@router.get("/recent", response_model=list[JellyfinAlbumSummary])
async def get_jellyfin_recent(
    limit: int = Query(default=20, ge=1, le=50),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinAlbumSummary]:
    return await service.get_recently_played(limit=limit)


@router.get("/favorites", response_model=list[JellyfinAlbumSummary])
async def get_jellyfin_favorites(
    limit: int = Query(default=20, ge=1, le=50),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinAlbumSummary]:
    return await service.get_favorites(limit=limit)


@router.get("/favorites/expanded", response_model=JellyfinFavoritesExpanded)
async def get_jellyfin_favorites_expanded(
    limit: int = Query(default=50, ge=1, le=100),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinFavoritesExpanded:
    try:
        return await service.get_favorites_expanded(limit=limit)
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting expanded favorites: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")
    except Exception:  # noqa: BLE001
        logger.exception("Unexpected error in expanded favorites")
        raise HTTPException(status_code=500, detail="Internal error fetching expanded favorites")


@router.get("/filters", response_model=JellyfinFilterFacets)
async def get_jellyfin_filter_facets(
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinFilterFacets:
    try:
        return await service.get_filter_facets()
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting filter facets: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/genres", response_model=list[str])
async def get_jellyfin_genres(
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[str]:
    try:
        return await service.get_genres()
    except ExternalServiceError as e:
        logger.error("Jellyfin service error getting genres: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Jellyfin")


@router.get("/genres/songs", response_model=JellyfinTrackPage)
async def get_jellyfin_genre_songs(
    genre: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinTrackPage:
    tracks, total = await service.get_songs_by_genre(genre, limit=limit, offset=offset)
    return JellyfinTrackPage(items=tracks, total=total, offset=offset, limit=limit)


@router.get("/instant-mix/artist/{artist_id}", response_model=list[JellyfinTrackInfo])
async def get_jellyfin_instant_mix_by_artist(
    artist_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinTrackInfo]:
    return await service.get_instant_mix_by_artist(artist_id, limit=limit)


@router.get("/instant-mix/genre", response_model=list[JellyfinTrackInfo])
async def get_jellyfin_instant_mix_by_genre(
    genre: str = Query(..., min_length=1),
    limit: int = Query(default=50, ge=1, le=100),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinTrackInfo]:
    return await service.get_instant_mix_by_genre(genre, limit=limit)


@router.get("/instant-mix/{item_id}", response_model=list[JellyfinTrackInfo])
async def get_jellyfin_instant_mix(
    item_id: str,
    limit: int = Query(default=50, ge=1, le=100),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinTrackInfo]:
    return await service.get_instant_mix(item_id, limit=limit)


@router.get("/stats", response_model=JellyfinLibraryStats)
async def get_jellyfin_stats(
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinLibraryStats:
    return await service.get_stats()


@router.get("/playlists", response_model=JellyfinPlaylistCollection)
async def get_jellyfin_playlists(
    current_user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=200),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
) -> JellyfinPlaylistCollection:
    try:
        return await service.list_user_playlists(
            current_user, playlist_service, limit=limit
        )
    except ExternalServiceError as e:
        logger.error("Failed to get Jellyfin playlists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to get Jellyfin playlists")


@router.get("/playlists/{playlist_id}", response_model=JellyfinPlaylistDetail)
async def get_jellyfin_playlist_detail(
    playlist_id: str,
    current_user: CurrentUserDep,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinPlaylistDetail:
    try:
        return await service.get_user_playlist_detail(playlist_id, current_user)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Jellyfin playlist not found")
    except ExternalServiceError as e:
        logger.error("Failed to get Jellyfin playlist %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to get Jellyfin playlist")


@router.post("/playlists/{playlist_id}/import", response_model=JellyfinImportResult)
async def import_jellyfin_playlist(
    playlist_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
    local_service=Depends(get_local_files_service),
    nd_service=Depends(get_navidrome_library_service),
    plex_service=Depends(get_plex_library_service),
) -> JellyfinImportResult:
    try:
        result = await service.import_playlist(playlist_id, playlist_service, requesting=current_user)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Jellyfin playlist not found")
    except ExternalServiceError as e:
        logger.error("Failed to import Jellyfin playlist %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to import Jellyfin playlist")

    if not result.already_imported:
        background_tasks.add_task(
            playlist_service.resolve_track_sources,
            result.droppedneedle_playlist_id,
            jf_service=service,
            local_service=local_service,
            nd_service=nd_service,
            plex_service=plex_service,
        )
    return result


@router.get("/sessions", response_model=JellyfinSessionsResponse)
async def get_jellyfin_sessions(
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinSessionsResponse:
    return await service.get_sessions()


@router.get("/similar/{item_id}", response_model=list[JellyfinAlbumSummary])
async def get_jellyfin_similar_items(
    item_id: str,
    limit: int = Query(10, ge=1, le=50),
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> list[JellyfinAlbumSummary]:
    return await service.get_similar_items(item_id, limit=limit)


@router.get("/lyrics/{item_id}", response_model=JellyfinLyricsResponse)
async def get_jellyfin_lyrics(
    item_id: str,
    service: JellyfinLibraryService = Depends(get_jellyfin_library_service),
) -> JellyfinLyricsResponse:
    lyrics = await service.get_lyrics(item_id)
    if lyrics is None:
        raise HTTPException(status_code=404, detail="Lyrics not available")
    return lyrics

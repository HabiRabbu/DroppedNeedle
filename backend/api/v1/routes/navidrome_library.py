import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Path, Query
from fastapi.responses import Response

from api.v1.schemas.navidrome import (
    NavidromeAlbumDetail,
    NavidromeAlbumInfoSchema,
    NavidromeAlbumMatch,
    NavidromeAlbumPage,
    NavidromeAlbumSummary,
    NavidromeArtistIndexResponse,
    NavidromeArtistInfoSchema,
    NavidromeArtistPage,
    NavidromeArtistSummary,
    NavidromeGenreSongsResponse,
    NavidromeHubResponse,
    NavidromeImportResult,
    NavidromeLibraryStats,
    NavidromeLyricsResponse,
    NavidromeMusicFolder,
    NavidromeNowPlayingResponse,
    NavidromePlaylistDetail,
    NavidromePlaylistSummary,
    NavidromeSearchResponse,
    NavidromeTrackInfo,
    NavidromeTrackPage,
)
from core.dependencies import (
    CurrentUserDep,
    get_jellyfin_library_service,
    get_local_files_service,
    get_navidrome_library_service,
    get_navidrome_repository,
    get_plex_library_service,
    get_playlist_service,
)
from core.exceptions import ExternalServiceError, ResourceNotFoundError
from infrastructure.msgspec_fastapi import MsgSpecRoute
from infrastructure.resilience.retry import CircuitOpenError
from repositories.navidrome_repository import NavidromeRepository
from services.navidrome_library_service import NavidromeLibraryService
from services.playlist_service import PlaylistService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/navidrome", tags=["navidrome-library"])


_SORT_MAP: dict[str, str] = {
    "name": "alphabeticalByName",
    "date_added": "newest",
    "year": "byYear",
}

_NEEDS_REVERSE: dict[tuple[str, str], bool] = {
    ("name", "desc"): True,
    ("date_added", ""): True,
    ("date_added", "asc"): True,
}


@router.get("/hub", response_model=NavidromeHubResponse)
async def get_navidrome_hub(
    current_user: CurrentUserDep,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
) -> NavidromeHubResponse:
    try:
        hub = await service.get_hub_data()
        imported_ids = await playlist_service.get_imported_source_ids("navidrome:", user_id=current_user.id)
        for p in hub.playlists:
            if p.id in imported_ids:
                p.is_imported = True
        return hub
    except ExternalServiceError as e:
        logger.error("Navidrome service error getting hub data: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/albums", response_model=NavidromeAlbumPage)
async def get_navidrome_albums(
    limit: int = Query(default=48, ge=1, le=500, alias="limit"),
    offset: int = Query(default=0, ge=0),
    sort_by: str = Query(default="name"),
    sort_order: str = Query(default=""),
    genre: str = Query(default=""),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeAlbumPage:
    subsonic_type = "byGenre" if genre else _SORT_MAP.get(sort_by, "alphabeticalByName")
    year_kwargs: dict[str, int] = {}
    if subsonic_type == "byYear":
        if sort_order == "desc":
            year_kwargs = {"from_year": 9999, "to_year": 0}
        else:
            year_kwargs = {"from_year": 0, "to_year": 9999}
    try:
        items = await service.get_albums(
            type=subsonic_type, size=limit, offset=offset, genre=genre if genre else None,
            **year_kwargs,
        )
    except ExternalServiceError as e:
        logger.error("Navidrome service error getting albums: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")

    if not genre and _NEEDS_REVERSE.get((sort_by, sort_order), False):
        items = list(reversed(items))

    try:
        stats = await service.get_stats()
        total = stats.total_albums if len(items) >= limit else offset + len(items)
    except (ExternalServiceError, CircuitOpenError):
        logger.warning("Navidrome stats unavailable, using heuristic pagination total")
        total = offset + len(items) + (1 if len(items) >= limit else 0)

    return NavidromeAlbumPage(items=items, total=total)


@router.get("/albums/{album_id}", response_model=NavidromeAlbumDetail)
async def get_navidrome_album_detail(
    album_id: str,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeAlbumDetail:
    result = await service.get_album_detail(album_id)
    if not result:
        raise HTTPException(status_code=404, detail="Album not found")
    return result


@router.get("/artists/browse", response_model=NavidromeArtistPage)
async def browse_navidrome_artists(
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query(""),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeArtistPage:
    try:
        items, total = await service.browse_artists(size=limit, offset=offset, search=search)
        return NavidromeArtistPage(items=items, total=total, offset=offset, limit=limit)
    except ExternalServiceError as e:
        logger.error("Navidrome service error browsing artists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/artists", response_model=list[NavidromeArtistSummary])
async def get_navidrome_artists(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[NavidromeArtistSummary]:
    return await service.get_artists()


@router.get("/artists/index", response_model=NavidromeArtistIndexResponse)
async def get_navidrome_artists_index(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeArtistIndexResponse:
    try:
        return await service.get_artists_index()
    except ExternalServiceError as e:
        logger.error("Navidrome service error getting artist index: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/artists/{artist_id}")
async def get_navidrome_artist_detail(
    artist_id: str,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> dict:
    result = await service.get_artist_detail(artist_id)
    if not result:
        raise HTTPException(status_code=404, detail="Artist not found")
    return result


@router.get("/tracks", response_model=NavidromeTrackPage)
async def browse_navidrome_tracks(
    limit: int = Query(48, ge=1, le=100),
    offset: int = Query(0, ge=0),
    search: str = Query(""),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeTrackPage:
    try:
        items, total = await service.browse_tracks(size=limit, offset=offset, search=search)
        return NavidromeTrackPage(items=items, total=total, offset=offset, limit=limit)
    except ExternalServiceError as e:
        logger.error("Navidrome service error browsing tracks: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/search", response_model=NavidromeSearchResponse)
async def search_navidrome(
    q: str = Query(..., min_length=1),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeSearchResponse:
    return await service.search(q)


@router.get("/recent", response_model=list[NavidromeAlbumSummary])
async def get_navidrome_recent(
    limit: int = Query(default=20, ge=1, le=50),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[NavidromeAlbumSummary]:
    return await service.get_recent(limit=limit)


@router.get("/favorites", response_model=list[NavidromeAlbumSummary])
async def get_navidrome_favorites(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[NavidromeAlbumSummary]:
    result = await service.get_favorites()
    return result.albums


@router.get("/favorites/expanded", response_model=NavidromeSearchResponse)
async def get_navidrome_favorites_expanded(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeSearchResponse:
    return await service.get_favorites()


@router.get("/genres", response_model=list[str])
async def get_navidrome_genres(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[str]:
    try:
        return await service.get_genres()
    except ExternalServiceError as e:
        logger.error("Navidrome service error getting genres: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/genres/songs", response_model=NavidromeGenreSongsResponse)
async def get_navidrome_multi_genre_songs(
    genres: str = Query(..., min_length=1),
    count: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeGenreSongsResponse:
    genre_list = [g.strip() for g in genres.split(",") if g.strip()]
    if not genre_list:
        return NavidromeGenreSongsResponse(songs=[], genre="")
    if len(genre_list) == 1:
        return await service.get_songs_by_genre(genre=genre_list[0], count=count, offset=offset)
    return await service.get_songs_by_genres(genres=genre_list, count=count, offset=offset)


@router.get("/genres/{genre}/songs", response_model=NavidromeGenreSongsResponse)
async def get_navidrome_genre_songs(
    genre: str = Path(...),
    count: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeGenreSongsResponse:
    try:
        return await service.get_songs_by_genre(genre=genre, count=count, offset=offset)
    except ExternalServiceError as e:
        logger.error("Navidrome service error getting songs by genre: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/music-folders", response_model=list[NavidromeMusicFolder])
async def get_navidrome_music_folders(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[NavidromeMusicFolder]:
    try:
        return await service.get_music_folders()
    except ExternalServiceError as e:
        logger.error("Navidrome service error getting music folders: %s", e)
        raise HTTPException(status_code=502, detail="Failed to communicate with Navidrome")


@router.get("/random", response_model=list[NavidromeTrackInfo])
async def get_navidrome_random(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
    size: int = Query(default=20, ge=1, le=50),
    genre: str | None = Query(default=None),
) -> list[NavidromeTrackInfo]:
    return await service.get_random_songs(size=size, genre=genre)


@router.get("/stats", response_model=NavidromeLibraryStats)
async def get_navidrome_stats(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeLibraryStats:
    return await service.get_stats()


@router.get("/cover/{cover_art_id}")
async def get_navidrome_cover(
    cover_art_id: str,
    size: int = Query(default=500, ge=32, le=1200),
    repo: NavidromeRepository = Depends(get_navidrome_repository),
) -> Response:
    try:
        image_bytes, content_type = await repo.get_cover_art(cover_art_id, size)
        return Response(
            content=image_bytes,
            media_type=content_type,
            headers={"Cache-Control": "public, max-age=31536000, immutable"},
        )
    except ExternalServiceError as e:
        logger.warning("Navidrome cover art failed for %s: %s", cover_art_id, e)
        raise HTTPException(status_code=502, detail="Failed to fetch cover art")


@router.get("/album-match/{album_id}", response_model=NavidromeAlbumMatch)
async def match_navidrome_album(
    album_id: str,
    name: str = Query(default=""),
    artist: str = Query(default=""),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeAlbumMatch:
    try:
        return await service.get_album_match(
            album_id=album_id, album_name=name, artist_name=artist,
        )
    except ExternalServiceError as e:
        logger.error("Failed to match Navidrome album %s: %s", album_id, e)
        raise HTTPException(status_code=502, detail="Failed to match Navidrome album")


@router.get("/playlists", response_model=list[NavidromePlaylistSummary])
async def get_navidrome_playlists(
    current_user: CurrentUserDep,
    limit: int = Query(default=50, ge=1, le=200),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
) -> list[NavidromePlaylistSummary]:
    try:
        playlists = await service.list_playlists(limit=limit)
        imported_ids = await playlist_service.get_imported_source_ids("navidrome:", user_id=current_user.id)
        for p in playlists:
            if p.id in imported_ids:
                p.is_imported = True
        return playlists
    except ExternalServiceError as e:
        logger.error("Failed to get Navidrome playlists: %s", e)
        raise HTTPException(status_code=502, detail="Failed to get Navidrome playlists")


@router.get("/playlists/{playlist_id}", response_model=NavidromePlaylistDetail)
async def get_navidrome_playlist_detail(
    playlist_id: str,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromePlaylistDetail:
    try:
        return await service.get_playlist_detail(playlist_id)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Navidrome playlist not found")
    except ExternalServiceError as e:
        logger.error("Failed to get Navidrome playlist %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to get Navidrome playlist")


@router.post("/playlists/{playlist_id}/import", response_model=NavidromeImportResult)
async def import_navidrome_playlist(
    playlist_id: str,
    background_tasks: BackgroundTasks,
    current_user: CurrentUserDep,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
    playlist_service: PlaylistService = Depends(get_playlist_service),
    jf_service=Depends(get_jellyfin_library_service),
    local_service=Depends(get_local_files_service),
    plex_service=Depends(get_plex_library_service),
) -> NavidromeImportResult:
    try:
        result = await service.import_playlist(playlist_id, playlist_service, requesting=current_user)
    except ResourceNotFoundError:
        raise HTTPException(status_code=404, detail="Navidrome playlist not found")
    except ExternalServiceError as e:
        logger.error("Failed to import Navidrome playlist %s: %s", playlist_id, e)
        raise HTTPException(status_code=502, detail="Failed to import Navidrome playlist")

    if not result.already_imported:
        background_tasks.add_task(
            playlist_service.resolve_track_sources,
            result.droppedneedle_playlist_id,
            jf_service=jf_service,
            local_service=local_service,
            nd_service=service,
            plex_service=plex_service,
        )
    return result


@router.get("/now-playing", response_model=NavidromeNowPlayingResponse)
async def get_navidrome_now_playing(
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeNowPlayingResponse:
    return await service.get_now_playing()


@router.get("/top-songs/{artist_name}", response_model=list[NavidromeTrackInfo])
async def get_navidrome_top_songs(
    artist_name: str = Path(..., min_length=1, max_length=256),
    count: int = Query(20, ge=1, le=50),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[NavidromeTrackInfo]:
    return await service.get_top_songs(artist_name, count=count)


@router.get("/similar-songs/{song_id}", response_model=list[NavidromeTrackInfo])
async def get_navidrome_similar_songs(
    song_id: str,
    count: int = Query(20, ge=1, le=50),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> list[NavidromeTrackInfo]:
    return await service.get_similar_songs(song_id, count=count)


@router.get("/artist-info/{artist_id}", response_model=NavidromeArtistInfoSchema)
async def get_navidrome_artist_info(
    artist_id: str,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeArtistInfoSchema:
    info = await service.get_artist_info(artist_id)
    if info is None:
        return NavidromeArtistInfoSchema(navidrome_id=artist_id)
    return info


@router.get("/album-info/{album_id}", response_model=NavidromeAlbumInfoSchema)
async def get_navidrome_album_info(
    album_id: str,
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeAlbumInfoSchema:
    info = await service.get_album_info(album_id)
    if info is None:
        return NavidromeAlbumInfoSchema(album_id=album_id)
    return info


@router.get("/lyrics/{song_id}", response_model=NavidromeLyricsResponse)
async def get_navidrome_lyrics(
    song_id: str,
    artist: str = Query("", description="Artist name for fallback lookup"),
    title: str = Query("", description="Track title for fallback lookup"),
    service: NavidromeLibraryService = Depends(get_navidrome_library_service),
) -> NavidromeLyricsResponse:
    lyrics = await service.get_lyrics(song_id, artist=artist, title=title)
    if lyrics is None:
        raise HTTPException(status_code=404, detail="Lyrics not available")
    return lyrics

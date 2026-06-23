from typing import Literal
from fastapi import APIRouter, Depends, Query
from api.v1.schemas.home import (
    HomeResponse,
    HomeIntegrationStatus,
    GenreDetailResponse,
    GenreArtistResponse,
    GenreArtistsBatchResponse,
    TrendingArtistsResponse,
    TrendingArtistsRangeResponse,
    PopularAlbumsResponse,
    PopularAlbumsRangeResponse,
)
from core.dependencies import get_home_service, get_home_charts_service
from core.dependencies.type_aliases import CurrentUserDep
from infrastructure.degradation import try_get_degradation_context
from infrastructure.msgspec_fastapi import MsgSpecRoute

import logging
import msgspec.structs
from services.home_service import HomeService
from services.home_charts_service import HomeChartsService

logger = logging.getLogger(__name__)

router = APIRouter(route_class=MsgSpecRoute, prefix="/home", tags=["home"])


@router.get("", response_model=HomeResponse)
async def get_home_data(
    current_user: CurrentUserDep,
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None, description="Data source: listenbrainz or lastfm"),
    home_service: HomeService = Depends(get_home_service),
):
    result = await home_service.get_home_data(user_id=current_user.id, source=source)
    ctx = try_get_degradation_context()
    if ctx is not None and ctx.has_degradation():
        result = msgspec.structs.replace(result, service_status=ctx.degraded_summary())
    return result


@router.get("/integration-status", response_model=HomeIntegrationStatus)
async def get_integration_status(
    home_service: HomeService = Depends(get_home_service)
):
    status = home_service.get_integration_status()
    # Refine localfiles via async lib check; never blank gating-critical status, so fall back on error.
    try:
        has_local = await home_service.has_local_files()
    except Exception as e:  # noqa: BLE001
        logger.warning("has_local_files check failed; keeping sync default: %s", e)
        has_local = status.localfiles
    return msgspec.structs.replace(status, localfiles=has_local)


@router.get("/genre/{genre_name}", response_model=GenreDetailResponse)
async def get_genre_detail(
    genre_name: str,
    limit: int = Query(default=50, ge=1, le=200),
    artist_offset: int = Query(default=0, ge=0),
    album_offset: int = Query(default=0, ge=0),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_genre_artists(
        genre=genre_name,
        limit=limit,
        artist_offset=artist_offset,
        album_offset=album_offset,
    )


@router.get("/trending/artists", response_model=TrendingArtistsResponse)
async def get_trending_artists(
    limit: int = Query(default=10, ge=1, le=25),
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_trending_artists(limit=limit, source=source)


@router.get("/trending/artists/{range_key}", response_model=TrendingArtistsRangeResponse)
async def get_trending_artists_by_range(
    range_key: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_trending_artists_by_range(
        range_key=range_key, limit=limit, offset=offset, source=source
    )


@router.get("/popular/albums", response_model=PopularAlbumsResponse)
async def get_popular_albums(
    limit: int = Query(default=10, ge=1, le=25),
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_popular_albums(limit=limit, source=source)


@router.get("/popular/albums/{range_key}", response_model=PopularAlbumsRangeResponse)
async def get_popular_albums_by_range(
    range_key: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_popular_albums_by_range(
        range_key=range_key, limit=limit, offset=offset, source=source
    )


@router.get("/your-top/albums", response_model=PopularAlbumsResponse)
async def get_your_top_albums(
    current_user: CurrentUserDep,
    limit: int = Query(default=10, ge=1, le=25),
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_your_top_albums(
        user_id=current_user.id, limit=limit, source=source
    )


@router.get("/your-top/albums/{range_key}", response_model=PopularAlbumsRangeResponse)
async def get_your_top_albums_by_range(
    current_user: CurrentUserDep,
    range_key: str,
    limit: int = Query(default=25, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source: Literal["listenbrainz", "lastfm"] | None = Query(default=None),
    charts_service: HomeChartsService = Depends(get_home_charts_service)
):
    return await charts_service.get_your_top_albums_by_range(
        user_id=current_user.id, range_key=range_key, limit=limit, offset=offset, source=source
    )


@router.get("/genre-artist/{genre_name}", response_model=GenreArtistResponse)
async def get_genre_artist(
    genre_name: str,
    home_service: HomeService = Depends(get_home_service)
):
    artist_mbid = await home_service.get_genre_artist(genre_name)
    return GenreArtistResponse(artist_mbid=artist_mbid)


@router.post("/genre-artists", response_model=GenreArtistsBatchResponse)
async def get_genre_artists_batch(
    genres: list[str],
    home_service: HomeService = Depends(get_home_service)
):
    results = await home_service.get_genre_artists_batch(genres)
    return GenreArtistsBatchResponse(genre_artists=results)

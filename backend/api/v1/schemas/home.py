from typing import Literal

from api.v1.schemas.common import IntegrationStatus
from api.v1.schemas.weekly_exploration import WeeklyExplorationSection
from infrastructure.msgspec_fastapi import AppStruct


class HomeArtist(AppStruct):
    name: str
    mbid: str | None = None
    local_id: str | None = None
    image_url: str | None = None
    listen_count: int | None = None
    in_library: bool = False
    source: str | None = None


class HomeAlbum(AppStruct):
    name: str
    mbid: str | None = None
    local_id: str | None = None
    artist_name: str | None = None
    artist_mbid: str | None = None
    image_url: str | None = None
    release_date: str | None = None
    listen_count: int | None = None
    in_library: bool = False
    requested: bool = False
    source: str | None = None


class HomeTrack(AppStruct):
    name: str
    mbid: str | None = None
    artist_name: str | None = None
    artist_mbid: str | None = None
    album_name: str | None = None
    listen_count: int | None = None
    listened_at: str | None = None
    image_url: str | None = None


class HomeGenre(AppStruct):
    name: str
    listen_count: int | None = None
    artist_count: int | None = None
    artist_mbid: str | None = None


class HomeSection(AppStruct):
    title: str
    type: str
    items: list[HomeArtist | HomeAlbum | HomeTrack | HomeGenre] = []
    source: str | None = None
    fallback_message: str | None = None
    connect_service: str | None = None
    radio_seed_type: str | None = None
    radio_seed_id: str | None = None


class ServicePrompt(AppStruct):
    service: str
    title: str
    description: str
    icon: str
    color: str
    features: list[str] = []


class HomeIntegrationStatus(IntegrationStatus):
    localfiles: bool = False


class DiscoverPreview(AppStruct):
    seed_artist: str
    seed_artist_mbid: str
    items: list[HomeArtist] = []


class GenreArtworkAlbum(AppStruct):
    album_id: str
    album_title: str
    cover_version: int
    album_artist_name: str | None = None


class GenreArtwork(AppStruct):
    kind: Literal["collage", "gradient"]
    version: str
    albums: list[GenreArtworkAlbum] = []


class HomeResponse(AppStruct):
    recently_added: HomeSection | None = None
    library_artists: HomeSection | None = None
    library_albums: HomeSection | None = None
    recommended_artists: HomeSection | None = None
    trending_artists: HomeSection | None = None
    popular_albums: HomeSection | None = None
    recently_played: HomeSection | None = None
    top_genres: HomeSection | None = None
    genre_list: HomeSection | None = None
    fresh_releases: HomeSection | None = None
    favorite_artists: HomeSection | None = None
    your_top_albums: HomeSection | None = None
    weekly_exploration: WeeklyExplorationSection | None = None
    service_prompts: list[ServicePrompt] = []
    integration_status: HomeIntegrationStatus | None = None
    genre_artwork: dict[str, GenreArtwork] = {}
    genre_artwork_schema_version: str = "v2"
    discover_preview: DiscoverPreview | None = None
    service_status: dict[str, str] | None = None
    # true while a fuller build is running in the background (frontend polls)
    refreshing: bool = False


class GenreLibrarySection(AppStruct):
    artists: list[HomeArtist] = []
    albums: list[HomeAlbum] = []
    artist_count: int = 0
    album_count: int = 0


class GenrePopularSection(AppStruct):
    artists: list[HomeArtist] = []
    albums: list[HomeAlbum] = []
    has_more_artists: bool = False
    has_more_albums: bool = False


class GenreDetailResponse(AppStruct):
    genre: str
    genre_artwork: GenreArtwork
    library: GenreLibrarySection | None = None
    popular: GenrePopularSection | None = None
    artists: list[HomeArtist] = []
    total_count: int | None = None


class TrendingTimeRange(AppStruct):
    range_key: str
    label: str
    featured: HomeArtist | None = None
    items: list[HomeArtist] = []
    total_count: int = 0


class TrendingArtistsResponse(AppStruct):
    this_week: TrendingTimeRange
    this_month: TrendingTimeRange
    this_year: TrendingTimeRange
    all_time: TrendingTimeRange


class PopularTimeRange(AppStruct):
    range_key: str
    label: str
    featured: HomeAlbum | None = None
    items: list[HomeAlbum] = []
    total_count: int = 0


class PopularAlbumsResponse(AppStruct):
    this_week: PopularTimeRange
    this_month: PopularTimeRange
    this_year: PopularTimeRange
    all_time: PopularTimeRange


class TrendingArtistsRangeResponse(AppStruct):
    range_key: str
    label: str
    items: list[HomeArtist] = []
    offset: int = 0
    limit: int = 25
    has_more: bool = False


class PopularAlbumsRangeResponse(AppStruct):
    range_key: str
    label: str
    items: list[HomeAlbum] = []
    offset: int = 0
    limit: int = 25
    has_more: bool = False

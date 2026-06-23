from typing import Literal

from models.search import SearchResult as SearchResult
from infrastructure.msgspec_fastapi import AppStruct

EnrichmentSource = Literal["listenbrainz", "lastfm", "none"]


class SearchResponse(AppStruct):
    artists: list[SearchResult] = []
    albums: list[SearchResult] = []
    top_artist: SearchResult | None = None
    top_album: SearchResult | None = None
    service_status: dict[str, str] | None = None


class SearchBucketResponse(AppStruct):
    bucket: str
    limit: int
    offset: int
    results: list[SearchResult] = []
    top_result: SearchResult | None = None


class ArtistEnrichment(AppStruct):
    musicbrainz_id: str
    release_group_count: int | None = None
    listen_count: int | None = None


class AlbumEnrichment(AppStruct):
    musicbrainz_id: str
    track_count: int | None = None
    listen_count: int | None = None


class ArtistEnrichmentRequest(AppStruct):
    musicbrainz_id: str
    name: str = ""


class AlbumEnrichmentRequest(AppStruct):
    musicbrainz_id: str
    artist_name: str = ""
    album_name: str = ""


class EnrichmentBatchRequest(AppStruct):
    artists: list[ArtistEnrichmentRequest] = []
    albums: list[AlbumEnrichmentRequest] = []


class EnrichmentResponse(AppStruct):
    artists: list[ArtistEnrichment] = []
    albums: list[AlbumEnrichment] = []
    source: EnrichmentSource = "none"


class SuggestResult(AppStruct):
    type: Literal["artist", "album"]
    title: str
    musicbrainz_id: str
    artist: str | None = None
    year: int | None = None
    in_library: bool = False
    requested: bool = False
    disambiguation: str | None = None
    score: int = 0


class SuggestResponse(AppStruct):
    results: list[SuggestResult] = []

from typing import Literal

from infrastructure.msgspec_fastapi import AppStruct


class TargetNativeArtist(AppStruct):
    id: str
    name: str
    musicbrainz_artist_id: str | None = None
    album_count: int = 0
    track_count: int = 0
    date_added: float | None = None
    row_revision: int = 1


class TargetNativeAlbum(AppStruct):
    id: str
    title: str
    artist_name: str
    artist_id: str
    musicbrainz_release_group_id: str | None = None
    musicbrainz_artist_id: str | None = None
    track_count: int = 0
    total_duration_seconds: float = 0
    total_size_bytes: int = 0
    format: str | None = None
    year: int | None = None
    is_compilation: bool = False
    cover_available: bool = False
    date_added: float | None = None
    sort_name: str | None = None
    original_release_date: str | None = None


class TargetNativeAlbumDetail(TargetNativeAlbum):
    row_revision: int = 1
    input_revision: str = ""
    identification_status: Literal[
        "identified",
        "needs_review",
        "keep_tagged",
        "local_metadata",
        "manual_identity_needs_review",
    ] = "local_metadata"
    review_id: str | None = None
    review_revision: int | None = None


class TargetNativeTrack(AppStruct):
    id: str
    title: str
    album_id: str
    album_title: str
    artist_id: str
    artist_name: str
    album_artist_id: str
    album_artist_name: str
    musicbrainz_recording_id: str | None = None
    musicbrainz_release_group_id: str | None = None
    musicbrainz_artist_id: str | None = None
    musicbrainz_album_artist_id: str | None = None
    disc_number: int = 1
    track_number: int = 0
    year: int | None = None
    genre: str | None = None
    duration_seconds: float = 0
    format: str = ""
    bit_rate: int | None = None
    sample_rate: int | None = None
    bit_depth: int | None = None
    channels: int | None = None
    file_size_bytes: int = 0
    date_added: float | None = None
    cover_available: bool = False
    current_tier: str | None = None
    below_cutoff: bool = False


class TargetNativeAlbumsResponse(AppStruct):
    items: list[TargetNativeAlbum] = []
    total: int = 0


class TargetNativeArtistsResponse(AppStruct):
    items: list[TargetNativeArtist] = []
    total: int = 0


class TargetNativeTracksResponse(AppStruct):
    items: list[TargetNativeTrack] = []
    total: int = 0
    offset: int = 0
    limit: int = 0


class TargetNativeStatsResponse(AppStruct):
    total_albums: int = 0
    total_artists: int = 0
    total_tracks: int = 0
    total_size_bytes: int = 0
    format_breakdown: dict[str, int] = {}
    review_count: int = 0
    local_only_count: int = 0
    last_scan_at: float | None = None


class TargetNativeAlbumStatusResponse(AppStruct):
    in_library: bool
    album_id: str
    track_count: int = 0
    tracks: list[TargetNativeTrack] = []


class TargetNativeProviderIdsResponse(AppStruct):
    musicbrainz_release_group_ids: list[str] = []


class TargetCatalogRemovalResponse(AppStruct):
    success: bool
    id: str
    removed_track_ids: list[str] = []

from api.v1.schemas.common import LastFmTagSchema
from models.album import AlbumInfo as AlbumInfo
from models.album import Track as Track
from infrastructure.msgspec_fastapi import AppStruct


class AlbumBasicInfo(AppStruct):
    title: str
    musicbrainz_id: str
    artist_name: str
    artist_id: str
    release_date: str | None = None
    year: int | None = None
    type: str | None = None
    disambiguation: str | None = None
    in_library: bool = False
    requested: bool = False
    cover_url: str | None = None
    album_thumb_url: str | None = None


class AlbumTracksInfo(AppStruct):
    tracks: list[Track] = []
    total_tracks: int = 0
    total_length: int | None = None
    label: str | None = None
    barcode: str | None = None
    country: str | None = None


class LastFmAlbumEnrichment(AppStruct):
    summary: str | None = None
    tags: list[LastFmTagSchema] = []
    listeners: int = 0
    playcount: int = 0
    url: str | None = None

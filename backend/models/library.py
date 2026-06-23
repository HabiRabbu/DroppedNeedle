from infrastructure.msgspec_fastapi import AppStruct
from infrastructure.validators import sanitize_optional_string


class LibraryAlbum(AppStruct):
    artist: str
    album: str
    year: int | None = None
    quality: str | None = None
    cover_url: str | None = None
    musicbrainz_id: str | None = None
    artist_mbid: str | None = None
    date_added: int | None = None

    def __post_init__(self) -> None:
        self.cover_url = sanitize_optional_string(self.cover_url)
        self.quality = sanitize_optional_string(self.quality)
        self.musicbrainz_id = sanitize_optional_string(self.musicbrainz_id)
        self.artist_mbid = sanitize_optional_string(self.artist_mbid)


class LibraryGroupedAlbum(AppStruct):
    title: str | None = None
    year: int | None = None
    cover_url: str | None = None


class LibraryGroupedArtist(AppStruct):
    artist: str
    albums: list[LibraryGroupedAlbum] = []

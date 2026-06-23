from infrastructure.msgspec_fastapi import AppStruct


class Track(AppStruct):
    position: int
    title: str
    disc_number: int = 1
    length: int | None = None
    recording_id: str | None = None


class AlbumInfo(AppStruct):
    title: str
    musicbrainz_id: str
    artist_name: str
    artist_id: str
    release_date: str | None = None
    year: int | None = None
    type: str | None = None
    label: str | None = None
    barcode: str | None = None
    country: str | None = None
    disambiguation: str | None = None
    tracks: list[Track] = []
    total_tracks: int = 0
    total_length: int | None = None
    in_library: bool = False
    requested: bool = False
    cover_url: str | None = None
    album_thumb_url: str | None = None
    album_back_url: str | None = None
    album_cdart_url: str | None = None
    album_spine_url: str | None = None
    album_3d_case_url: str | None = None
    album_3d_flat_url: str | None = None
    album_3d_face_url: str | None = None
    album_3d_thumb_url: str | None = None
    service_status: dict[str, str] | None = None

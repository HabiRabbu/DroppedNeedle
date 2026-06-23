from infrastructure.msgspec_fastapi import AppStruct


class SearchResult(AppStruct):
    type: str
    title: str
    musicbrainz_id: str
    artist: str | None = None
    year: int | None = None
    in_library: bool = False
    requested: bool = False
    cover_url: str | None = None
    album_thumb_url: str | None = None
    thumb_url: str | None = None
    fanart_url: str | None = None
    banner_url: str | None = None
    disambiguation: str | None = None
    type_info: str | None = None
    score: int = 0

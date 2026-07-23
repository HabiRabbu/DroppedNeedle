"""Live-verified LRCLIB response models."""

import msgspec


class LrclibLyricsResponse(msgspec.Struct):
    id: int = 0
    name: str = ""
    track_name: str = msgspec.field(name="trackName", default="")
    artist_name: str = msgspec.field(name="artistName", default="")
    album_name: str = msgspec.field(name="albumName", default="")
    duration: float = 0.0
    instrumental: bool = False
    plain_lyrics: str | None = msgspec.field(name="plainLyrics", default=None)
    synced_lyrics: str | None = msgspec.field(name="syncedLyrics", default=None)
    lyrics_file: str | None = msgspec.field(name="lyricsfile", default=None)


class LrclibErrorResponse(msgspec.Struct):
    status_code: int = msgspec.field(name="statusCode", default=0)
    name: str = ""
    message: str = ""

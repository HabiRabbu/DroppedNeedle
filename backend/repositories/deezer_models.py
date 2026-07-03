"""Deezer + iTunes wire models for 30-second track previews.

Live-verified 2026-07-03:
- Deezer ``GET https://api.deezer.com/search?q=artist:"X" track:"Y"&limit=N``
  returns ``{"data": [{id, title, title_short, duration, preview, artist: {name}, ...}]}``
  where ``preview`` is a 30s MP3 URL carrying an ``hdnea=exp=...`` expiry -
  resolve just-in-time, never cache the URL long-term.
- Deezer ``GET /search/album?q=artist:"X" album:"Y"`` returns album hits with ``id``;
  ``GET /album/{id}/tracks`` returns ordered tracks each with ``preview`` +
  ``track_position``.
- iTunes ``GET https://itunes.apple.com/search?term=...&entity=song&limit=N``
  returns ``{"resultCount": N, "results": [{artistName, trackName, collectionName,
  previewUrl, trackTimeMillis}]}`` (~30s AAC previews). Top result can be a cover -
  callers must verify ``artistName``.

All fields default-tolerant: either provider omitting a field must never fail a decode.
"""

import msgspec


class DeezerArtist(msgspec.Struct, kw_only=True):
    id: int | None = None
    name: str = ""


class DeezerTrack(msgspec.Struct, kw_only=True):
    id: int | None = None
    title: str = ""
    title_short: str = ""
    duration: int | None = None
    track_position: int | None = None
    preview: str = ""
    artist: DeezerArtist | None = None


class DeezerTrackSearchResponse(msgspec.Struct, kw_only=True):
    data: list[DeezerTrack] = []


class DeezerAlbum(msgspec.Struct, kw_only=True):
    id: int | None = None
    title: str = ""
    artist: DeezerArtist | None = None


class DeezerAlbumSearchResponse(msgspec.Struct, kw_only=True):
    data: list[DeezerAlbum] = []


class DeezerAlbumTracksResponse(msgspec.Struct, kw_only=True):
    data: list[DeezerTrack] = []


class ITunesTrack(msgspec.Struct, kw_only=True, rename=None):
    artist_name: str = msgspec.field(name="artistName", default="")
    track_name: str = msgspec.field(name="trackName", default="")
    collection_name: str = msgspec.field(name="collectionName", default="")
    preview_url: str = msgspec.field(name="previewUrl", default="")
    track_time_millis: int | None = msgspec.field(name="trackTimeMillis", default=None)
    track_number: int | None = msgspec.field(name="trackNumber", default=None)


class ITunesSearchResponse(msgspec.Struct, kw_only=True):
    result_count: int = msgspec.field(name="resultCount", default=0)
    results: list[ITunesTrack] = []


class PreviewTrack(msgspec.Struct, kw_only=True):
    """Provider-neutral preview result used inside the backend."""

    title: str
    artist_name: str = ""
    preview_url: str = ""
    duration_s: int | None = None
    position: int | None = None

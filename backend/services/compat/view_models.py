"""Neutral View DTOs - the one internal model both shims read/write.

Internal ids + internal units (seconds, unix timestamps). Per-user fields are
filled only when a user context is supplied.
"""

from __future__ import annotations

from infrastructure.msgspec_fastapi import AppStruct


class ViewArtist(AppStruct):
    artist_mbid: str
    name: str
    album_count: int | None = None
    date_added: int | None = None      # unix seconds
    starred_at: float | None = None    # per-user


class ViewAlbum(AppStruct):
    rg_mbid: str
    title: str
    artist_name: str | None = None
    artist_mbid: str | None = None
    year: int | None = None
    genre: str | None = None           # dominant genre across tracks
    track_count: int | None = None
    total_duration_seconds: float | None = None
    cover_available: bool = False
    date_added: int | None = None
    is_compilation: bool = False
    starred_at: float | None = None    # per-user
    play_count: int | None = None      # per-user (optional)


class ViewTrack(AppStruct):
    file_id: str
    title: str
    album_title: str
    rg_mbid: str | None = None
    artist_name: str = ""
    artist_mbid: str | None = None
    album_artist_name: str | None = None
    album_artist_mbid: str | None = None
    track_number: int = 0
    disc_number: int = 1
    year: int | None = None
    genre: str | None = None
    duration_seconds: float = 0.0
    file_format: str = ""
    bitrate: int | None = None         # kbps
    sample_rate: int | None = None     # Hz
    bit_depth: int | None = None
    channels: int | None = None
    file_size_bytes: int = 0
    recording_mbid: str | None = None
    file_path: str = ""                # NEVER serialized to clients - stream use only
    created_at: float | None = None    # unix seconds (imported_at)
    starred_at: float | None = None    # per-user
    play_count: int | None = None      # per-user


class ViewPlaylist(AppStruct):
    id: str
    name: str
    description: str | None = None
    is_public: bool = False
    owner_id: str = ""
    track_count: int = 0
    total_duration_seconds: float | None = None
    created_at: float | None = None
    changed_at: float | None = None
    cover_available: bool = False


class ViewGenre(AppStruct):
    name: str
    song_count: int = 0
    album_count: int = 0

"""Immutable Library Management lyrics and ReplayGain projections."""

from __future__ import annotations

from typing import Literal

import msgspec


class LyricsCandidate(msgspec.Struct, frozen=True, kw_only=True):
    provider: Literal["lrclib"] = "lrclib"
    provider_id: int
    track_name: str
    artist_name: str
    album_name: str
    duration_seconds: float
    instrumental: bool
    plain_lyrics: str | None
    synced_lyrics: str | None
    provider_revision: str


class LyricsLookupResult(msgspec.Struct, frozen=True, kw_only=True):
    found: bool
    candidate: LyricsCandidate | None = None


class LyricsProjection(msgspec.Struct, frozen=True, kw_only=True):
    status: Literal["disabled", "available", "not_found", "deferred", "mismatch"]
    plain_lyrics: str | None = None
    synced_lyrics: str | None = None
    provider_id: int | None = None
    provider_revision: str | None = None
    reason: str | None = None


class ReplayGainTrackResult(msgspec.Struct, frozen=True, kw_only=True):
    source_path: str
    track_gain_db: float
    track_peak: float
    album_gain_db: float | None = None
    album_peak: float | None = None


class ReplayGainAnalysis(msgspec.Struct, frozen=True, kw_only=True):
    status: Literal["available", "deferred"]
    tracks: tuple[ReplayGainTrackResult, ...] = ()
    analyzer: str = "loudgain"
    analyzer_version: str | None = None
    reason: str | None = None

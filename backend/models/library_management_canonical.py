"""Immutable canonical metadata contracts for Library Management."""

from __future__ import annotations

from typing import Literal

import msgspec


class ImmutableManagementStruct(msgspec.Struct, frozen=True, kw_only=True):
    pass


class CanonicalDate(ImmutableManagementStruct):
    value: str
    precision: Literal["year", "month", "day"]


class CanonicalArtistCredit(ImmutableManagementStruct):
    display_name: str
    credited_name: str
    canonical_name: str
    sort_name: str
    artist_mbid: str
    join_phrase: str = ""


class CanonicalRelationshipCredit(ImmutableManagementStruct):
    role: str
    source_type: str
    display_name: str
    canonical_name: str
    sort_name: str
    artist_mbid: str
    attributes: tuple[str, ...] = ()
    begin_date: str | None = None
    end_date: str | None = None


class CanonicalLabel(ImmutableManagementStruct):
    name: str | None = None
    label_mbid: str | None = None
    catalog_number: str | None = None


class CanonicalIdentifierSet(ImmutableManagementStruct):
    release_group_mbid: str
    release_mbid: str
    release_track_mbid: str | None = None
    recording_mbid: str | None = None
    album_artist_mbids: tuple[str, ...] = ()
    artist_mbids: tuple[str, ...] = ()
    work_mbids: tuple[str, ...] = ()
    isrcs: tuple[str, ...] = ()


class CanonicalGenre(ImmutableManagementStruct):
    display_name: str
    provider_entity: str
    genre_mbid: str | None = None
    count: int | None = None


class CanonicalTrackDocument(ImmutableManagementStruct):
    local_track_id: str
    source_track_revision: int
    source_identity_revision: int
    title: str
    artist_credits: tuple[CanonicalArtistCredit, ...]
    relationship_credits: tuple[CanonicalRelationshipCredit, ...]
    identifiers: CanonicalIdentifierSet
    track_number: int
    track_number_text: str
    total_tracks: int
    disc_number: int
    total_discs: int
    disc_subtitle: str | None = None
    media_format: str | None = None
    duration_milliseconds: int | None = None
    work_title: str | None = None
    movement: str | None = None
    movement_number: int | None = None
    movement_count: int | None = None
    genres: tuple[CanonicalGenre, ...] = ()


class CanonicalMedium(ImmutableManagementStruct):
    position: int
    title: str | None
    format: str | None
    track_count: int
    tracks: tuple[CanonicalTrackDocument, ...]


class CanonicalReleaseDocument(ImmutableManagementStruct):
    local_album_id: str
    source_album_revision: int
    source_identity_revision: int
    title: str
    artist_credits: tuple[CanonicalArtistCredit, ...]
    identifiers: CanonicalIdentifierSet
    date: CanonicalDate | None
    original_date: CanonicalDate | None
    release_status: str | None
    release_country: str | None
    primary_release_type: str | None
    secondary_release_types: tuple[str, ...]
    packaging: str | None
    barcode: str | None
    asin: str | None
    language: str | None
    script: str | None
    compilation: bool
    total_discs: int
    labels: tuple[CanonicalLabel, ...]
    genres: tuple[CanonicalGenre, ...]
    media: tuple[CanonicalMedium, ...]


class AcceptedTrackManagementIdentity(ImmutableManagementStruct):
    local_track_id: str
    track_revision: int
    identity_revision: int | None
    recording_mbid: str | None
    release_mbid: str | None
    release_track_mbid: str | None
    medium_position: int | None
    release_track_position: int | None


class AcceptedAlbumManagementIdentity(ImmutableManagementStruct):
    local_album_id: str
    album_revision: int
    identity_revision: int | None
    release_group_mbid: str | None
    release_mbid: str | None
    tracks: tuple[AcceptedTrackManagementIdentity, ...]


class IncomingTrackManagementMapping(ImmutableManagementStruct):
    local_track_id: str
    medium_position: int
    release_track_position: int
    recording_mbid: str | None = None
    release_track_mbid: str | None = None


class CanonicalReleaseProjection(ImmutableManagementStruct):
    document: CanonicalReleaseDocument
    metadata_snapshot_id: str
    input_hash: str
    payload_sha256: str

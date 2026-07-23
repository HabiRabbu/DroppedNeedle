"""Tolerant MusicBrainz response models used by Library Management.

These structs mirror the verified third-party JSON surface recorded in
``musicbrainz_MANAGEMENT_API_NOTES.md``.  They deliberately remain repository-local:
services project them into immutable DroppedNeedle domain documents before use.
"""

from __future__ import annotations

import msgspec


class MbManagementAlias(msgspec.Struct):
    name: str = ""
    sort_name: str = msgspec.field(name="sort-name", default="")
    locale: str | None = None
    type: str | None = None
    primary: bool | None = None
    begin_date: str | None = msgspec.field(name="begin-date", default=None)
    end_date: str | None = msgspec.field(name="end-date", default=None)


class MbManagementGenre(msgspec.Struct):
    id: str = ""
    name: str = ""
    count: int | None = None
    disambiguation: str = ""


class MbManagementArtist(msgspec.Struct):
    id: str = ""
    name: str = ""
    sort_name: str = msgspec.field(name="sort-name", default="")
    disambiguation: str = ""
    country: str | None = None
    aliases: list[MbManagementAlias] = msgspec.field(default_factory=list)
    genres: list[MbManagementGenre] = msgspec.field(default_factory=list)


class MbManagementArtistCredit(msgspec.Struct):
    name: str = ""
    joinphrase: str = ""
    artist: MbManagementArtist = msgspec.field(default_factory=MbManagementArtist)


class MbManagementWorkRelation(msgspec.Struct):
    target_type: str = msgspec.field(name="target-type", default="")
    type: str = ""
    type_id: str = msgspec.field(name="type-id", default="")
    direction: str = ""
    attributes: list[str] = msgspec.field(default_factory=list)
    attribute_values: dict[str, str] = msgspec.field(
        name="attribute-values", default_factory=dict
    )
    target_credit: str = msgspec.field(name="target-credit", default="")
    begin: str | None = None
    end: str | None = None
    ended: bool = False
    artist: MbManagementArtist | None = None


class MbManagementWork(msgspec.Struct):
    id: str = ""
    title: str = ""
    type: str | None = None
    type_id: str = msgspec.field(name="type-id", default="")
    disambiguation: str = ""
    attributes: list[str] = msgspec.field(default_factory=list)
    languages: list[str] = msgspec.field(default_factory=list)
    relations: list[MbManagementWorkRelation] = msgspec.field(default_factory=list)


class MbManagementRelation(msgspec.Struct):
    target_type: str = msgspec.field(name="target-type", default="")
    type: str = ""
    type_id: str = msgspec.field(name="type-id", default="")
    direction: str = ""
    attributes: list[str] = msgspec.field(default_factory=list)
    attribute_values: dict[str, str] = msgspec.field(
        name="attribute-values", default_factory=dict
    )
    target_credit: str = msgspec.field(name="target-credit", default="")
    begin: str | None = None
    end: str | None = None
    ended: bool = False
    artist: MbManagementArtist | None = None
    work: MbManagementWork | None = None


class MbManagementRecording(msgspec.Struct):
    id: str = ""
    title: str = ""
    length: int | None = None
    video: bool = False
    disambiguation: str = ""
    first_release_date: str | None = msgspec.field(
        name="first-release-date", default=None
    )
    artist_credit: list[MbManagementArtistCredit] = msgspec.field(
        name="artist-credit", default_factory=list
    )
    isrcs: list[str] = msgspec.field(default_factory=list)
    aliases: list[MbManagementAlias] = msgspec.field(default_factory=list)
    genres: list[MbManagementGenre] = msgspec.field(default_factory=list)
    relations: list[MbManagementRelation] = msgspec.field(default_factory=list)


class MbManagementTrack(msgspec.Struct):
    id: str = ""
    title: str = ""
    position: int = 0
    number: str = ""
    length: int | None = None
    artist_credit: list[MbManagementArtistCredit] = msgspec.field(
        name="artist-credit", default_factory=list
    )
    recording: MbManagementRecording = msgspec.field(
        default_factory=MbManagementRecording
    )


class MbManagementMedium(msgspec.Struct):
    id: str = ""
    position: int = 0
    title: str = ""
    format: str | None = None
    track_count: int = msgspec.field(name="track-count", default=0)
    track_offset: int = msgspec.field(name="track-offset", default=0)
    tracks: list[MbManagementTrack] = msgspec.field(default_factory=list)


class MbManagementLabel(msgspec.Struct):
    id: str = ""
    name: str = ""
    sort_name: str = msgspec.field(name="sort-name", default="")
    disambiguation: str = ""


class MbManagementLabelInfo(msgspec.Struct):
    catalog_number: str = msgspec.field(name="catalog-number", default="")
    label: MbManagementLabel | None = None


class MbManagementReleaseGroup(msgspec.Struct):
    id: str = ""
    title: str = ""
    first_release_date: str | None = msgspec.field(
        name="first-release-date", default=None
    )
    primary_type: str | None = msgspec.field(name="primary-type", default=None)
    primary_type_id: str = msgspec.field(name="primary-type-id", default="")
    secondary_types: list[str] = msgspec.field(
        name="secondary-types", default_factory=list
    )
    secondary_type_ids: list[str] = msgspec.field(
        name="secondary-type-ids", default_factory=list
    )
    disambiguation: str = ""
    artist_credit: list[MbManagementArtistCredit] = msgspec.field(
        name="artist-credit", default_factory=list
    )
    aliases: list[MbManagementAlias] = msgspec.field(default_factory=list)
    genres: list[MbManagementGenre] = msgspec.field(default_factory=list)
    relations: list[MbManagementRelation] = msgspec.field(default_factory=list)


class MbManagementArea(msgspec.Struct):
    id: str = ""
    name: str = ""
    sort_name: str = msgspec.field(name="sort-name", default="")
    iso_3166_1_codes: list[str] = msgspec.field(
        name="iso-3166-1-codes", default_factory=list
    )


class MbManagementReleaseEvent(msgspec.Struct):
    date: str = ""
    area: MbManagementArea | None = None


class MbManagementTextRepresentation(msgspec.Struct):
    language: str | None = None
    script: str | None = None


class MbManagementCoverArtArchive(msgspec.Struct):
    artwork: bool = False
    count: int = 0
    front: bool = False
    back: bool = False
    darkened: bool = False


class MbManagementRelease(msgspec.Struct):
    id: str = ""
    title: str = ""
    status: str | None = None
    status_id: str = msgspec.field(name="status-id", default="")
    quality: str | None = None
    date: str | None = None
    country: str | None = None
    barcode: str | None = None
    asin: str | None = None
    packaging: str | None = None
    packaging_id: str = msgspec.field(name="packaging-id", default="")
    disambiguation: str = ""
    text_representation: MbManagementTextRepresentation = msgspec.field(
        name="text-representation", default_factory=MbManagementTextRepresentation
    )
    release_events: list[MbManagementReleaseEvent] = msgspec.field(
        name="release-events", default_factory=list
    )
    cover_art_archive: MbManagementCoverArtArchive = msgspec.field(
        name="cover-art-archive", default_factory=MbManagementCoverArtArchive
    )
    artist_credit: list[MbManagementArtistCredit] = msgspec.field(
        name="artist-credit", default_factory=list
    )
    label_info: list[MbManagementLabelInfo] = msgspec.field(
        name="label-info", default_factory=list
    )
    media: list[MbManagementMedium] = msgspec.field(default_factory=list)
    release_group: MbManagementReleaseGroup = msgspec.field(
        name="release-group", default_factory=MbManagementReleaseGroup
    )
    genres: list[MbManagementGenre] = msgspec.field(default_factory=list)
    relations: list[MbManagementRelation] = msgspec.field(default_factory=list)

"""Typed plans and reconciliation reports for the legacy catalog import."""

from __future__ import annotations

from typing import Literal

import msgspec

from infrastructure.msgspec_fastapi import AppStruct
from models.library_work import MigrationProvenance
from models.local_catalog import (
    CatalogMembership,
    LocalAlbumAlias,
    LocalAlbumExternalIdentity,
    LocalArtistAlias,
    LocalArtistExternalIdentity,
    LocalArtworkAssociation,
    LocalTrackExternalIdentity,
)


class MigrationReferenceCount(AppStruct):
    kind: str
    source: int = 0
    mapped: int = 0
    duplicate: int = 0
    unresolved: int = 0
    retained: int = 0
    tombstoned: int = 0
    user_id: str | None = None


class MigrationReview(AppStruct):
    id: str
    local_album_id: str | None = None
    local_track_id: str | None = None
    state: Literal["needs_review", "keep_tagged", "excluded", "resolved"] = (
        "needs_review"
    )
    reason_code: str = ""
    input_revision: str = ""
    created_at: float = 0.0
    updated_at: float = 0.0
    decided_at: float | None = None


class MigrationTombstone(AppStruct):
    id: str
    source_kind: str
    source_key: str
    title: str
    legacy_file_id: str | None = None
    artist_name: str | None = None
    album_name: str | None = None
    source_type: str | None = None
    created_at: float = 0.0


class LegacyCatalogImportBundle(AppStruct):
    membership: CatalogMembership
    album_identity: LocalAlbumExternalIdentity | None = None
    track_identities: list[LocalTrackExternalIdentity] = msgspec.field(
        default_factory=list
    )
    artist_identities: list[LocalArtistExternalIdentity] = msgspec.field(
        default_factory=list
    )
    artist_aliases: list[LocalArtistAlias] = msgspec.field(default_factory=list)
    album_aliases: list[LocalAlbumAlias] = msgspec.field(default_factory=list)
    artwork: LocalArtworkAssociation | None = None
    reviews: list[MigrationReview] = msgspec.field(default_factory=list)
    provenance: list[MigrationProvenance] = msgspec.field(default_factory=list)


class LegacyCatalogImportPlan(AppStruct):
    source_revision: str
    root_revision: str
    bundles: list[LegacyCatalogImportBundle] = msgspec.field(default_factory=list)
    reference_provenance: list[MigrationProvenance] = msgspec.field(
        default_factory=list
    )
    tombstones: list[MigrationTombstone] = msgspec.field(default_factory=list)
    reference_counts: list[MigrationReferenceCount] = msgspec.field(
        default_factory=list
    )
    blockers: list[str] = msgspec.field(default_factory=list)
    warnings: list[str] = msgspec.field(default_factory=list)
    network_calls: int = 0
    tag_reads: int = 0
    fingerprints: int = 0
    embedded_art_reads: int = 0


class MigrationDryRunReport(AppStruct):
    migration_id: str
    source_revision: str
    root_revision: str
    state: Literal["ready", "blocked", "applied"]
    identified_albums: int
    local_only_albums: int
    identified_tracks: int
    local_only_tracks: int
    artists: int
    reference_counts: list[MigrationReferenceCount] = msgspec.field(
        default_factory=list
    )
    blockers: list[str] = msgspec.field(default_factory=list)
    warnings: list[str] = msgspec.field(default_factory=list)
    network_calls: int = 0
    tag_reads: int = 0
    fingerprints: int = 0
    embedded_art_reads: int = 0

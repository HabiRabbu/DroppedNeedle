"""Immutable selection and preview contracts for Library Management planning."""

from __future__ import annotations

from typing import Literal

import msgspec

from api.v1.schemas.library_management import (
    LibraryManagementProfile,
    NamingScriptSettings,
    TaggingScriptSettings,
)


ManagementSelectionKind = Literal["roots", "artists", "albums", "tracks", "filter"]


class LibraryManagementCatalogFilter(msgspec.Struct, frozen=True, kw_only=True):
    search: str | None = None
    genre: str | None = None
    from_year: int | None = None
    to_year: int | None = None
    artist_ids: tuple[str, ...] = ()
    album_artist_only: bool = False


class LibraryManagementSelection(msgspec.Struct, frozen=True, kw_only=True):
    kind: ManagementSelectionKind
    ids: tuple[str, ...] = ()
    catalog_filter: LibraryManagementCatalogFilter | None = None


class LibraryManagementRootScope(msgspec.Struct, frozen=True, kw_only=True):
    root_id: str
    relative_prefix: str | None = None


class NormalizedLibraryManagementSelection(msgspec.Struct, frozen=True, kw_only=True):
    kind: ManagementSelectionKind
    ids: tuple[str, ...] = ()
    root_scopes: tuple[LibraryManagementRootScope, ...] = ()
    catalog_filter: LibraryManagementCatalogFilter | None = None
    expand_album_bundles: bool = False
    requested_track_ids: tuple[str, ...] = ()
    expanded_track_count: int = 0


class PinnedLibraryManagementProfile(msgspec.Struct, frozen=True, kw_only=True):
    profile: LibraryManagementProfile
    naming_script: NamingScriptSettings
    external_artwork_naming_script: NamingScriptSettings | None = None
    tagging_scripts: tuple[TaggingScriptSettings, ...] = ()
    recycle_bin_path: str = ""


class LibraryManagementSelectionCursor(msgspec.Struct, frozen=True, kw_only=True):
    album_id: str
    disc_number: int
    track_number: int
    track_id: str
    next_ordinal: int
    bundle_ordinal: int


class LibraryManagementSelectionSubject(msgspec.Struct, frozen=True, kw_only=True):
    ordinal: int
    bundle_ordinal: int
    bundle_first: bool
    local_album_id: str
    local_track_id: str
    album_revision: int
    track_revision: int
    root_id: str
    relative_path: str
    file_path: str
    file_size_bytes: int
    file_mtime_ns: int
    stat_revision: str
    tag_revision: str
    availability: str
    applied_policy: str
    file_format: str
    disc_number: int
    track_number: int


class LibraryManagementSelectionPage(msgspec.Struct, frozen=True, kw_only=True):
    subjects: tuple[LibraryManagementSelectionSubject, ...]
    next_cursor: LibraryManagementSelectionCursor | None
    complete: bool


class LibraryManagementPreviewHandle(msgspec.Struct, frozen=True, kw_only=True):
    job_id: str
    preview_token: str
    created_at: float
    expires_at: float
    existing: bool = False


class LibraryManagementPreviewSummary(msgspec.Struct, frozen=True, kw_only=True):
    item_count: int = 0
    bundle_count: int = 0
    eligible_count: int = 0
    warning_count: int = 0
    blocked_count: int = 0
    stale_count: int = 0
    no_change_count: int = 0
    tag_change_count: int = 0
    artwork_change_count: int = 0
    path_change_count: int = 0
    sidecar_change_count: int = 0
    estimated_temporary_bytes: int = 0
    expanded_track_count: int = 0
    reasons: dict[str, int] = msgspec.field(default_factory=dict)
    roots: dict[str, int] = msgspec.field(default_factory=dict)
    formats: dict[str, int] = msgspec.field(default_factory=dict)
    metadata_snapshot_ids: tuple[str, ...] = ()

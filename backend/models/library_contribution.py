from __future__ import annotations

from typing import Literal

import msgspec

from infrastructure.msgspec_fastapi import AppStruct

ContributionState = Literal[
    "draft",
    "ready",
    "seeded",
    "verifying",
    "linked",
    "needs_review",
    "stale",
    "cancelled",
]
ContributionNextAction = Literal[
    "edit_draft",
    "refresh_discogs",
    "run_duplicate_check",
    "attach_existing",
    "seed_musicbrainz",
    "retry_verification",
    "rebuild",
    "cancel",
]
ContributionFieldSource = Literal["local", "discogs", "entered_here"]


class ReleaseTextField(AppStruct):
    value: str | None = None
    source: ContributionFieldSource = "local"


class ReleaseTrackSnapshot(AppStruct):
    local_track_id: str
    disc_number: int
    track_number: int
    title: str
    artist_name: str | None = None
    duration_seconds: float | None = None
    duration_reliable: bool = False


class ReleaseMediumSnapshot(AppStruct):
    position: int
    title: str | None = None
    tracks: list[ReleaseTrackSnapshot] = msgspec.field(default_factory=list)


class LocalReleaseSnapshot(AppStruct):
    schema_version: int = 1
    local_album_id: str = ""
    local_artist_id: str = ""
    album_row_revision: int = 1
    input_revision: str = ""
    title: str = ""
    album_artist_name: str = ""
    artist_kind: str = "unknown"
    musicbrainz_artist_id: str | None = None
    musicbrainz_release_group_id: str | None = None
    musicbrainz_release_id: str | None = None
    release_date: str | None = None
    year: int | None = None
    is_compilation: bool = False
    captured_at: float = 0.0
    media: list[ReleaseMediumSnapshot] = msgspec.field(default_factory=list)


class ReleaseTrackDraft(AppStruct):
    local_track_id: str
    disc_number: int
    track_number: int
    title: ReleaseTextField
    artist_name: ReleaseTextField
    duration_seconds: float | None = None


class ReleaseMediumDraft(AppStruct):
    position: int
    title: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    format: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    tracks: list[ReleaseTrackDraft] = msgspec.field(default_factory=list)


class ReleaseDraft(AppStruct):
    schema_version: int = 1
    title: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    artist_credit: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    release_date: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    country: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    label: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    catalogue_number: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    barcode: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    packaging: ReleaseTextField = msgspec.field(default_factory=ReleaseTextField)
    media: list[ReleaseMediumDraft] = msgspec.field(default_factory=list)


class SourceReference(AppStruct):
    provider: str
    entity_type: str
    external_id: str
    canonical_url: str
    fetched_at: float | None = None


class TrackAlignment(AppStruct):
    local_track_id: str
    provider_position: str | None = None
    classification: Literal["exact", "partial", "conflicting", "unmatched"] = (
        "unmatched"
    )


class ContributionSourceSelection(AppStruct):
    schema_version: int = 1
    sources: list[SourceReference] = msgspec.field(default_factory=list)
    alignments: list[TrackAlignment] = msgspec.field(default_factory=list)


class DiscogsReleaseCandidate(AppStruct):
    release_id: str
    title: str
    artist_name: str
    canonical_url: str
    year: int | None = None
    country: str | None = None
    label: str | None = None
    catalogue_number: str | None = None
    format_summary: str | None = None
    track_count: int | None = None
    master_id: str | None = None
    fetched_at: float = 0.0


class DiscogsArtistCredit(AppStruct):
    name: str
    credited_name: str | None = None
    join_phrase: str = ""
    artist_id: str | None = None
    canonical_url: str | None = None


class DiscogsLabel(AppStruct):
    name: str
    catalogue_number: str | None = None
    label_id: str | None = None
    canonical_url: str | None = None


class DiscogsIdentifier(AppStruct):
    type: str
    value: str
    description: str | None = None


class DiscogsFormat(AppStruct):
    name: str
    quantity: int | None = None
    descriptions: list[str] = msgspec.field(default_factory=list)
    text: str | None = None


class DiscogsTrack(AppStruct):
    source_position: str | None
    number: int | None
    title: str
    duration_seconds: float | None = None
    heading: bool = False
    artists: list[DiscogsArtistCredit] = msgspec.field(default_factory=list)


class DiscogsMedium(AppStruct):
    position: int
    title: str | None = None
    format: str | None = None
    tracks: list[DiscogsTrack] = msgspec.field(default_factory=list)


class DiscogsRelease(AppStruct):
    release_id: str
    master_id: str | None
    canonical_release_url: str
    canonical_master_url: str | None
    title: str
    artist_name: str
    artists: list[DiscogsArtistCredit] = msgspec.field(default_factory=list)
    released_date: str | None = None
    year: int | None = None
    country: str | None = None
    labels: list[DiscogsLabel] = msgspec.field(default_factory=list)
    identifiers: list[DiscogsIdentifier] = msgspec.field(default_factory=list)
    barcode: str | None = None
    formats: list[DiscogsFormat] = msgspec.field(default_factory=list)
    media: list[DiscogsMedium] = msgspec.field(default_factory=list)
    source_fetched_at: float = 0.0


class DiscogsSourceView(AppStruct):
    release: DiscogsRelease | None = None
    expired: bool = False
    expires_at: float | None = None


class DuplicateCandidate(AppStruct):
    release_mbid: str | None
    release_group_mbid: str | None = None
    title: str = ""
    artist_name: str = ""
    evidence_kind: Literal[
        "exact_discogs_url", "release_group", "barcode", "similar"
    ] = "similar"
    exact: bool = False
    differences: list[str] = msgspec.field(default_factory=list)


class DuplicateCheckResult(AppStruct):
    schema_version: int = 1
    checked_at: float = 0.0
    input_revision: str = ""
    candidates: list[DuplicateCandidate] = msgspec.field(default_factory=list)
    different_edition_confirmed: bool = False


class MusicBrainzUrlResolution(AppStruct):
    resource_url: str
    release_mbids: list[str] = msgspec.field(default_factory=list)
    release_group_mbids: list[str] = msgspec.field(default_factory=list)
    artist_mbids: list[str] = msgspec.field(default_factory=list)
    label_mbids: list[str] = msgspec.field(default_factory=list)


class MusicBrainzVerifiedTrack(AppStruct):
    title: str
    position: int
    disc_number: int
    duration_seconds: float | None = None
    recording_mbid: str | None = None


class MusicBrainzVerifiedRelease(AppStruct):
    release_mbid: str
    release_group_mbid: str
    title: str
    artist_name: str
    artist_mbid: str | None = None
    date: str | None = None
    country: str | None = None
    status: str | None = None
    packaging: str | None = None
    barcode: str | None = None
    label: str | None = None
    catalogue_number: str | None = None
    tracks: list[MusicBrainzVerifiedTrack] = msgspec.field(default_factory=list)


class MusicBrainzDuplicateFacts(AppStruct):
    title: str
    artist_name: str
    barcode: str | None = None
    country: str | None = None
    date: str | None = None


class MusicBrainzSeedField(AppStruct):
    name: str
    value: str


class MusicBrainzSeed(AppStruct):
    action_url: str
    method: Literal["POST"] = "POST"
    fields: list[MusicBrainzSeedField] = msgspec.field(default_factory=list)
    contribution_revision: int = 1
    expires_at: float = 0.0


class ContributionValidationIssue(AppStruct):
    code: str
    field: str
    message: str


class ContributionRecord(AppStruct):
    id: str
    local_album_id: str
    created_by_user_id: str | None
    updated_by_user_id: str | None
    state: ContributionState
    album_row_revision: int
    input_revision: str
    local_snapshot: LocalReleaseSnapshot
    draft: ReleaseDraft
    source_selection: ContributionSourceSelection
    provider_snapshot_expires_at: float | None = None
    discogs_source: DiscogsSourceView | None = None
    duplicate_result: DuplicateCheckResult | None = None
    duplicate_checked_at: float | None = None
    result_release_mbid: str | None = None
    result_source: Literal["callback", "manual"] | None = None
    result_received_at: float | None = None
    seeded_at: float | None = None
    terminal_at: float | None = None
    created_at: float = 0.0
    updated_at: float = 0.0
    row_revision: int = 1
    input_is_current: bool = True
    validation: list[ContributionValidationIssue] = msgspec.field(default_factory=list)
    next_actions: list[ContributionNextAction] = msgspec.field(default_factory=list)

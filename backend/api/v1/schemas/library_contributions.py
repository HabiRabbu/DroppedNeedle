import msgspec

from models.library_contribution import (
    ContributionRecord,
    DiscogsReleaseCandidate,
    MusicBrainzSeed,
    ReleaseDraft,
)
from infrastructure.msgspec_fastapi import AppStruct


class LibraryContributionResponse(ContributionRecord):
    pass


class LibraryContributionDraftUpdateRequest(AppStruct):
    expected_row_revision: int
    draft: ReleaseDraft


class LibraryContributionRevisionRequest(AppStruct):
    expected_row_revision: int


class DiscogsReleaseSearchRequest(AppStruct):
    query: str | None = None


class DiscogsReleaseSearchResponse(AppStruct):
    results: list[DiscogsReleaseCandidate] = msgspec.field(default_factory=list)


class DiscogsSourceSelectRequest(AppStruct):
    expected_row_revision: int
    release_id_or_url: str


class ContributionDuplicateCheckRequest(AppStruct):
    expected_row_revision: int
    different_edition_confirmed: bool = False


class ContributionAttachExistingRequest(AppStruct):
    expected_row_revision: int
    release_mbid: str


class ContributionMusicBrainzResultRequest(AppStruct):
    expected_row_revision: int
    release_id_or_url: str
    replace_existing_result: bool = False


class MusicBrainzSeedResponse(MusicBrainzSeed):
    pass

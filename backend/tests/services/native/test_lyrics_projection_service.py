from unittest.mock import AsyncMock

import pytest

from api.v1.schemas.library_management import LyricsManagementSettings
from core.exceptions import LrclibApiError
from models.library_management_canonical import (
    CanonicalArtistCredit,
    CanonicalIdentifierSet,
    CanonicalReleaseDocument,
    CanonicalTrackDocument,
)
from models.library_management_enrichment import LyricsCandidate, LyricsLookupResult
from services.native.lyrics_projection_service import LyricsProjectionService


def _release() -> CanonicalReleaseDocument:
    identifiers = CanonicalIdentifierSet(
        release_group_mbid="rg",
        release_mbid="release",
    )
    return CanonicalReleaseDocument(
        local_album_id="album",
        source_album_revision=1,
        source_identity_revision=1,
        title="Rumours",
        artist_credits=(),
        identifiers=identifiers,
        date=None,
        original_date=None,
        release_status=None,
        release_country=None,
        primary_release_type="Album",
        secondary_release_types=(),
        packaging=None,
        barcode=None,
        asin=None,
        language=None,
        script=None,
        compilation=False,
        total_discs=1,
        labels=(),
        genres=(),
        media=(),
    )


def _track() -> CanonicalTrackDocument:
    return CanonicalTrackDocument(
        local_track_id="track",
        source_track_revision=1,
        source_identity_revision=1,
        title="The Chain",
        artist_credits=(
            CanonicalArtistCredit(
                display_name="Fleetwood Mac",
                credited_name="Fleetwood Mac",
                canonical_name="Fleetwood Mac",
                sort_name="Fleetwood Mac",
                artist_mbid="artist",
            ),
        ),
        relationship_credits=(),
        identifiers=CanonicalIdentifierSet(
            release_group_mbid="rg",
            release_mbid="release",
            release_track_mbid="release-track",
            recording_mbid="recording",
        ),
        track_number=1,
        track_number_text="1",
        total_tracks=1,
        disc_number=1,
        total_discs=1,
        duration_milliseconds=270_000,
    )


def _candidate(**changes) -> LyricsCandidate:  # noqa: ANN003
    values = {
        "provider_id": 42,
        "track_name": "The Chain",
        "artist_name": "Fleetwood Mac",
        "album_name": "Rumours",
        "duration_seconds": 270.1,
        "instrumental": False,
        "plain_lyrics": "Plain",
        "synced_lyrics": "[00:01.00]Synced",
        "provider_revision": "revision",
    }
    values.update(changes)
    return LyricsCandidate(**values)


@pytest.mark.asyncio
async def test_exact_normalized_signature_projects_plain_and_synced() -> None:
    repository = AsyncMock()
    repository.get_exact_lyrics.return_value = LyricsLookupResult(
        found=True,
        candidate=_candidate(
            track_name="  THE   CHAIN ",
            artist_name="fleetwood mac",
        ),
    )
    service = LyricsProjectionService(repository)

    result = await service.project(
        settings=LyricsManagementSettings(enabled=True),
        canonical_release=_release(),
        canonical_track=_track(),
        duration_seconds=270.0,
    )

    assert result.status == "available"
    assert result.plain_lyrics == "Plain"
    assert result.synced_lyrics == "[00:01.000]Synced"
    repository.get_exact_lyrics.assert_awaited_once_with(
        track_name="The Chain",
        artist_name="Fleetwood Mac",
        album_name="Rumours",
        duration_seconds=270,
    )


@pytest.mark.asyncio
async def test_mismatched_name_or_duration_is_not_admitted() -> None:
    repository = AsyncMock()
    repository.get_exact_lyrics.return_value = LyricsLookupResult(
        found=True,
        candidate=_candidate(album_name="Rumours Deluxe", duration_seconds=280),
    )

    result = await LyricsProjectionService(repository).project(
        settings=LyricsManagementSettings(enabled=True),
        canonical_release=_release(),
        canonical_track=_track(),
        duration_seconds=270.0,
    )

    assert result.status == "mismatch"
    assert result.plain_lyrics is None
    assert result.provider_id == 42


@pytest.mark.asyncio
async def test_absence_and_outage_have_distinct_statuses() -> None:
    repository = AsyncMock()
    repository.get_exact_lyrics.return_value = LyricsLookupResult(found=False)
    service = LyricsProjectionService(repository)
    missing = await service.project(
        settings=LyricsManagementSettings(enabled=True),
        canonical_release=_release(),
        canonical_track=_track(),
        duration_seconds=270.0,
    )
    repository.get_exact_lyrics.side_effect = LrclibApiError("offline")
    deferred = await service.project(
        settings=LyricsManagementSettings(enabled=True),
        canonical_release=_release(),
        canonical_track=_track(),
        duration_seconds=270.0,
    )

    assert missing.status == "not_found"
    assert deferred.status == "deferred"


@pytest.mark.asyncio
async def test_disabled_setting_does_not_call_provider() -> None:
    repository = AsyncMock()

    result = await LyricsProjectionService(repository).project(
        settings=LyricsManagementSettings(),
        canonical_release=_release(),
        canonical_track=_track(),
        duration_seconds=270.0,
    )

    assert result.status == "disabled"
    repository.get_exact_lyrics.assert_not_called()

import json
import sqlite3
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ValidationError
from models.library_contribution import (
    DiscogsMedium,
    DiscogsRelease,
    DiscogsTrack,
    LocalReleaseSnapshot,
    ReleaseMediumSnapshot,
    ReleaseTrackSnapshot,
)
from services.native.library_contribution_service import LibraryContributionService
from tests.services.native.test_library_contribution_service import _service


@pytest.mark.parametrize(
    "value, expected",
    [
        ("249504", "249504"),
        ("https://www.discogs.com/release/249504", "249504"),
        (
            "https://discogs.com/release/249504-Rick-Astley-Never-Gonna-Give-You-Up",
            "249504",
        ),
    ],
)
def test_discogs_release_parser_accepts_fixed_safe_forms(
    value: str, expected: str
) -> None:
    assert LibraryContributionService.parse_discogs_release_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "http://www.discogs.com/release/1",
        "https://evil.example/release/1",
        "https://www.discogs.com:443/release/1",
        "https://user@www.discogs.com/release/1",
        "https://www.discogs.com/master/1",
        "https://www.discogs.com/release/1?next=https://evil.example",
        "https://www.discogs.com/release/1#fragment",
        "0",
        "../release/1",
    ],
)
def test_discogs_release_parser_rejects_ssrf_and_non_release_forms(value: str) -> None:
    with pytest.raises(ValidationError):
        LibraryContributionService.parse_discogs_release_id(value)


def test_alignment_preserves_local_order_and_marks_conflicts() -> None:
    snapshot = LocalReleaseSnapshot(
        media=[
            ReleaseMediumSnapshot(
                position=1,
                tracks=[
                    ReleaseTrackSnapshot(
                        local_track_id="local-1",
                        disc_number=1,
                        track_number=1,
                        title="Same song",
                    ),
                    ReleaseTrackSnapshot(
                        local_track_id="local-2",
                        disc_number=1,
                        track_number=2,
                        title="Local title",
                    ),
                ],
            )
        ]
    )
    release = DiscogsRelease(
        release_id="1",
        master_id=None,
        canonical_release_url="https://www.discogs.com/release/1",
        canonical_master_url=None,
        title="Album",
        artist_name="Artist",
        media=[
            DiscogsMedium(
                position=1,
                tracks=[
                    DiscogsTrack(source_position="1", number=1, title="Same song"),
                    DiscogsTrack(
                        source_position="2", number=2, title="Completely different"
                    ),
                ],
            )
        ],
    )
    alignments = LibraryContributionService._align_tracks(snapshot, release)
    assert [item.local_track_id for item in alignments] == ["local-1", "local-2"]
    assert alignments[0].classification == "exact"
    assert alignments[1].classification in {"conflicting", "unmatched"}


@pytest.mark.asyncio
async def test_search_is_narrow_user_initiated() -> None:
    store = AsyncMock()
    repository = AsyncMock()
    service = LibraryContributionService(store, repository)
    contribution = AsyncMock()
    contribution.state = "ready"
    contribution.local_snapshot.album_artist_name = "Artist"
    contribution.local_snapshot.title = "Album"
    service.get = AsyncMock(return_value=contribution)
    repository.search_releases.return_value = []
    assert await service.search_discogs("draft-1", None) == []
    call = repository.search_releases.await_args
    assert call.args[0] == "Artist Album"
    assert call.kwargs["limit"] == 8


@pytest.mark.asyncio
async def test_expired_discogs_values_are_purged_but_source_identity_is_retained(
    tmp_path,
) -> None:
    base, path = _service(tmp_path)
    fetched_at = 1_900_000_000.0
    release = DiscogsRelease(
        release_id="123",
        master_id=None,
        canonical_release_url="https://www.discogs.com/release/123",
        canonical_master_url=None,
        title="Album",
        artist_name="Artist",
        country="GB",
        source_fetched_at=fetched_at,
        media=[
            DiscogsMedium(
                position=1,
                tracks=[DiscogsTrack(source_position="1", number=1, title="Track")],
            )
        ],
    )
    repository = AsyncMock()
    repository.get_release.return_value = release
    service = LibraryContributionService(base._store, repository)
    created = await service.create("album-1", "curator-1")
    selected = await service.select_discogs(
        created.id,
        release_id_or_url="123",
        expected_row_revision=created.row_revision,
        actor_user_id="curator-1",
    )
    selected.draft.country.value = "GB"
    selected.draft.country.source = "discogs"
    updated = await service.update(
        selected.id,
        expected_row_revision=selected.row_revision,
        draft=selected.draft,
        actor_user_id="curator-1",
    )

    assert (
        await service.purge_expired_provider_data(now=fetched_at + 6 * 60 * 60 + 1) == 1
    )
    purged = await service.get(updated.id)

    assert purged.draft.country.value is None
    assert purged.draft.country.source == "local"
    assert purged.discogs_source is not None
    assert purged.discogs_source.expired is True
    assert purged.source_selection.sources[0].external_id == "123"
    assert purged.source_selection.alignments == []
    with sqlite3.connect(path) as connection:
        row = connection.execute(
            "SELECT resolved_draft_json, provider_snapshot_expires_at, "
            "duplicate_result_json, seed_snapshot_json "
            "FROM library_contribution_drafts WHERE id = ?",
            (updated.id,),
        ).fetchone()
    persisted = json.loads(row[0])
    assert persisted["country"] == {"value": None, "source": "local"}
    assert row[1:] == (None, None, None)

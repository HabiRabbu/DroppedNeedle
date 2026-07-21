import sqlite3
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ContributionExactDuplicateError, ValidationError
from infrastructure.cache.memory_cache import InMemoryCache
from models.library_contribution import (
    DiscogsMedium,
    DiscogsRelease,
    DiscogsTrack,
    MusicBrainzUrlResolution,
    MusicBrainzVerifiedRelease,
    MusicBrainzVerifiedTrack,
)
from services.native.library_contribution_service import LibraryContributionService
from tests.services.native.test_library_contribution_service import _service

_RELEASE_MBID = "11111111-1111-4111-8111-111111111111"
_GROUP_MBID = "22222222-2222-4222-8222-222222222222"
_ARTIST_MBID = "33333333-3333-4333-8333-333333333333"


def _verified() -> MusicBrainzVerifiedRelease:
    return MusicBrainzVerifiedRelease(
        release_mbid=_RELEASE_MBID,
        release_group_mbid=_GROUP_MBID,
        title="Album",
        artist_name="Artist",
        artist_mbid=_ARTIST_MBID,
        date="2001",
        tracks=[
            MusicBrainzVerifiedTrack(
                title="Track",
                position=1,
                disc_number=1,
                duration_seconds=180,
                recording_mbid="44444444-4444-4444-8444-444444444444",
            )
        ],
    )


def _musicbrainz() -> AsyncMock:
    repository = AsyncMock()
    repository.search_duplicate_releases.return_value = [_verified()]
    repository.get_release_for_verification.return_value = _verified()
    repository.resolve_url.return_value = MusicBrainzUrlResolution(resource_url="")
    return repository


@pytest.mark.asyncio
async def test_similar_candidate_requires_confirmation_then_builds_safe_ordered_seed(
    tmp_path,
) -> None:
    base, path = _service(tmp_path)
    musicbrainz = _musicbrainz()
    service = LibraryContributionService(
        base._store, musicbrainz_repository=musicbrainz, cache=InMemoryCache()
    )
    created = await service.create("album-1", "curator-1")
    ready = await service.update(
        created.id,
        expected_row_revision=created.row_revision,
        draft=created.draft,
        actor_user_id="curator-1",
    )
    review = await service.check_duplicates(
        ready.id,
        expected_row_revision=ready.row_revision,
        actor_user_id="curator-1",
        different_edition_confirmed=False,
    )
    assert review.state == "needs_review"
    assert review.duplicate_result is not None
    assert review.duplicate_result.candidates[0].evidence_kind == "similar"

    confirmed = await service.check_duplicates(
        review.id,
        expected_row_revision=review.row_revision,
        actor_user_id="curator-1",
        different_edition_confirmed=True,
    )
    assert confirmed.state == "ready"
    seed = await service.create_musicbrainz_seed(
        confirmed.id,
        expected_row_revision=confirmed.row_revision,
        actor_user_id="curator-1",
        public_base_url="https://music.example",
    )
    assert seed.action_url == "https://musicbrainz.org/release/add"
    assert seed.method == "POST"
    assert seed.fields[0].name == "name"
    assert [field.name for field in seed.fields][-2:] == ["edit_note", "redirect_uri"]
    redirect = seed.fields[-1].value
    assert redirect.startswith(
        "https://music.example/api/v1/library/contributions/musicbrainz/callback?token="
    )
    assert "/private" not in repr(seed)
    token = parse_qs(urlsplit(redirect).query)["token"][0]
    callback_contribution_id = await service.consume_musicbrainz_callback(
        token, _RELEASE_MBID
    )
    assert callback_contribution_id == confirmed.id
    musicbrainz.get_release_for_verification.assert_not_awaited()
    with sqlite3.connect(path) as connection:
        stored = connection.execute(
            "SELECT seed_snapshot_json FROM library_contribution_drafts WHERE id = ?",
            (confirmed.id,),
        ).fetchone()[0]
        file_path = connection.execute(
            "SELECT file_path FROM local_tracks WHERE id = 'track-1'"
        ).fetchone()[0]
    assert "token=" not in stored
    assert file_path == "/private/music/track.flac"


@pytest.mark.asyncio
async def test_attach_existing_uses_evidence_gate_and_atomically_links_album_and_artist(
    tmp_path,
) -> None:
    base, path = _service(tmp_path)
    service = LibraryContributionService(
        base._store, musicbrainz_repository=_musicbrainz(), cache=InMemoryCache()
    )
    created = await service.create("album-1", "curator-1")
    ready = await service.update(
        created.id,
        expected_row_revision=created.row_revision,
        draft=created.draft,
        actor_user_id="curator-1",
    )
    checked = await service.check_duplicates(
        ready.id,
        expected_row_revision=ready.row_revision,
        actor_user_id="curator-1",
        different_edition_confirmed=False,
    )
    linked = await service.attach_existing(
        checked.id,
        release_mbid=_RELEASE_MBID,
        expected_row_revision=checked.row_revision,
        actor_user_id="curator-1",
    )
    assert linked.state == "linked"
    assert linked.input_is_current is True
    with sqlite3.connect(path) as connection:
        album = connection.execute(
            "SELECT release_group_mbid, release_mbid FROM local_album_external_identities "
            "WHERE local_album_id = 'album-1'"
        ).fetchone()
        artist = connection.execute(
            "SELECT provider_artist_id FROM local_artist_external_identities "
            "WHERE local_artist_id = 'artist-1'"
        ).fetchone()
        track = connection.execute(
            "SELECT recording_mbid, release_mbid FROM local_track_external_identities "
            "WHERE local_track_id = 'track-1'"
        ).fetchone()
        attempt_count = connection.execute(
            "SELECT COUNT(*) FROM library_identification_attempts "
            "WHERE trigger = 'contribution_submission'"
        ).fetchone()[0]
        evidence_count = connection.execute(
            "SELECT COUNT(*) FROM library_identification_evidence"
        ).fetchone()[0]
    assert album == (_GROUP_MBID, _RELEASE_MBID)
    assert artist == (_ARTIST_MBID,)
    assert track == (
        "44444444-4444-4444-8444-444444444444",
        _RELEASE_MBID,
    )
    assert attempt_count == 1
    assert evidence_count == 1


@pytest.mark.asyncio
async def test_attach_existing_creates_merge_candidate_for_shared_artist_identity(
    tmp_path,
) -> None:
    base, path = _service(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, kind, created_at, updated_at) "
            "VALUES ('artist-2', 'Other Artist', 'other artist', 'person', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_artist_external_identities "
            "(local_artist_id, provider, provider_artist_id, decision_source, selected_at) "
            "VALUES ('artist-2', 'musicbrainz', ?, 'manual', 1)",
            (_ARTIST_MBID,),
        )
    service = LibraryContributionService(
        base._store, musicbrainz_repository=_musicbrainz(), cache=InMemoryCache()
    )
    created = await service.create("album-1", "curator-1")
    ready = await service.update(
        created.id,
        expected_row_revision=created.row_revision,
        draft=created.draft,
        actor_user_id="curator-1",
    )
    checked = await service.check_duplicates(
        ready.id,
        expected_row_revision=ready.row_revision,
        actor_user_id="curator-1",
        different_edition_confirmed=False,
    )

    linked = await service.attach_existing(
        checked.id,
        release_mbid=_RELEASE_MBID,
        expected_row_revision=checked.row_revision,
        actor_user_id="curator-1",
    )

    assert linked.state == "linked"
    with sqlite3.connect(path) as connection:
        local_identity = connection.execute(
            "SELECT provider_artist_id FROM local_artist_external_identities "
            "WHERE local_artist_id = 'artist-1'"
        ).fetchone()
        merge_reason = connection.execute(
            "SELECT reason_code FROM local_artist_merge_candidates "
            "WHERE left_artist_id = 'artist-1' AND right_artist_id = 'artist-2'"
        ).fetchone()
    assert local_identity is None
    assert merge_reason == ("SHARED_PROVIDER_IDENTITY",)


@pytest.mark.asyncio
async def test_seed_reuses_verified_release_group_and_artist_mbids(tmp_path) -> None:
    base, path = _service(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO local_album_external_identities "
            "(local_album_id, provider, release_group_mbid, decision_source, selected_at) "
            "VALUES ('album-1', 'musicbrainz', ?, 'manual', 1)",
            (_GROUP_MBID,),
        )
        connection.execute(
            "INSERT INTO local_artist_external_identities "
            "(local_artist_id, provider, provider_artist_id, decision_source, selected_at) "
            "VALUES ('artist-1', 'musicbrainz', ?, 'manual', 1)",
            (_ARTIST_MBID,),
        )
    musicbrainz = _musicbrainz()
    musicbrainz.search_duplicate_releases.return_value = []
    service = LibraryContributionService(
        base._store, musicbrainz_repository=musicbrainz, cache=InMemoryCache()
    )
    created = await service.create("album-1", "curator-1")
    ready = await service.update(
        created.id,
        expected_row_revision=created.row_revision,
        draft=created.draft,
        actor_user_id="curator-1",
    )
    checked = await service.check_duplicates(
        ready.id,
        expected_row_revision=ready.row_revision,
        actor_user_id="curator-1",
        different_edition_confirmed=False,
    )
    seed = await service.create_musicbrainz_seed(
        checked.id,
        expected_row_revision=checked.row_revision,
        actor_user_id="curator-1",
        public_base_url="https://music.example",
    )
    fields = [(field.name, field.value) for field in seed.fields]

    assert ("release_group", _GROUP_MBID) in fields
    assert ("artist_credit.names.0.mbid", _ARTIST_MBID) in fields


@pytest.mark.asyncio
async def test_exact_discogs_relationship_blocks_new_release_seed(tmp_path) -> None:
    base, _path = _service(tmp_path)
    discogs_release = DiscogsRelease(
        release_id="123",
        master_id=None,
        canonical_release_url="https://www.discogs.com/release/123",
        canonical_master_url=None,
        title="Album",
        artist_name="Artist",
        source_fetched_at=1_900_000_000,
        media=[
            DiscogsMedium(
                position=1,
                tracks=[
                    DiscogsTrack(
                        source_position="1",
                        number=1,
                        title="Track",
                        duration_seconds=180,
                    )
                ],
            )
        ],
    )
    discogs = AsyncMock()
    discogs.get_release.return_value = discogs_release
    musicbrainz = _musicbrainz()
    musicbrainz.resolve_url.return_value = MusicBrainzUrlResolution(
        resource_url=discogs_release.canonical_release_url,
        release_mbids=[_RELEASE_MBID],
    )
    service = LibraryContributionService(
        base._store,
        discogs_repository=discogs,
        musicbrainz_repository=musicbrainz,
    )
    created = await service.create("album-1", "curator-1")
    selected = await service.select_discogs(
        created.id,
        release_id_or_url="123",
        expected_row_revision=created.row_revision,
        actor_user_id="curator-1",
    )
    ready = await service.update(
        selected.id,
        expected_row_revision=selected.row_revision,
        draft=selected.draft,
        actor_user_id="curator-1",
    )
    checked = await service.check_duplicates(
        ready.id,
        expected_row_revision=ready.row_revision,
        actor_user_id="curator-1",
        different_edition_confirmed=False,
    )
    assert checked.next_actions.count("attach_existing") == 1
    with pytest.raises(ContributionExactDuplicateError):
        await service.create_musicbrainz_seed(
            checked.id,
            expected_row_revision=checked.row_revision,
            actor_user_id="curator-1",
            public_base_url="https://music.example",
        )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (_RELEASE_MBID, _RELEASE_MBID),
        (f"https://musicbrainz.org/release/{_RELEASE_MBID}", _RELEASE_MBID),
        (f"https://musicbrainz.org/release/{_RELEASE_MBID}/", _RELEASE_MBID),
    ],
)
def test_musicbrainz_result_parser_accepts_only_fixed_release_references(
    value: str, expected: str
) -> None:
    assert LibraryContributionService.parse_musicbrainz_release_id(value) == expected


@pytest.mark.parametrize(
    "value",
    [
        "not-an-mbid",
        f"http://musicbrainz.org/release/{_RELEASE_MBID}",
        f"https://evil.example/release/{_RELEASE_MBID}",
        f"https://musicbrainz.org:444/release/{_RELEASE_MBID}",
        f"https://musicbrainz.org/release/{_RELEASE_MBID}?next=https://evil.example",
    ],
)
def test_musicbrainz_result_parser_rejects_non_release_targets(value: str) -> None:
    with pytest.raises(ValidationError):
        LibraryContributionService.parse_musicbrainz_release_id(value)


@pytest.mark.asyncio
async def test_callback_rejects_oversized_release_mbid_before_store_lookup() -> None:
    store = AsyncMock()
    service = LibraryContributionService(store)

    with pytest.raises(ValidationError, match="release MBID is invalid"):
        await service.consume_musicbrainz_callback("a" * 43, "b" * 65)

    store.consume_library_contribution_callback_token.assert_not_awaited()

import sqlite3
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ExternalServiceError
from infrastructure.cache.memory_cache import InMemoryCache
from models.library_contribution import (
    MusicBrainzVerifiedRelease,
    MusicBrainzVerifiedTrack,
)
from services.native.library_contribution_service import LibraryContributionService
from services.native.library_contribution_verification_worker import (
    LibraryContributionVerificationWorker,
)
from tests.services.native.test_library_contribution_service import _service

_RELEASE_MBID = "11111111-1111-4111-8111-111111111111"
_GROUP_MBID = "22222222-2222-4222-8222-222222222222"
_ARTIST_MBID = "33333333-3333-4333-8333-333333333333"
_RECORDING_MBID = "44444444-4444-4444-8444-444444444444"


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
                recording_mbid=_RECORDING_MBID,
            )
        ],
    )


async def _returned_contribution(tmp_path):
    base, path = _service(tmp_path)
    musicbrainz = AsyncMock()
    musicbrainz.resolve_url.return_value.release_mbids = []
    musicbrainz.search_duplicate_releases.return_value = []
    musicbrainz.get_release_for_verification.return_value = _verified()
    service = LibraryContributionService(
        base._store,
        musicbrainz_repository=musicbrainz,
        cache=InMemoryCache(),
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
    redirect_uri = next(
        field.value for field in seed.fields if field.name == "redirect_uri"
    )
    token = parse_qs(urlsplit(redirect_uri).query)["token"][0]
    contribution_id = await service.consume_musicbrainz_callback(token, _RELEASE_MBID)
    return service, musicbrainz, path, contribution_id


@pytest.mark.asyncio
async def test_verified_result_persists_evidence_and_attaches_all_identities_atomically(
    tmp_path,
) -> None:
    service, musicbrainz, path, contribution_id = await _returned_contribution(tmp_path)
    worker = LibraryContributionVerificationWorker(service._store, service, musicbrainz)

    assert await worker.run_once("worker-1", now=time.time() + 1) == "linked"
    linked = await service.get(contribution_id)

    assert linked.state == "linked"
    assert linked.result_release_mbid == _RELEASE_MBID
    with sqlite3.connect(path) as connection:
        album_identity = connection.execute(
            "SELECT release_group_mbid, release_mbid, decision_source, attempt_id "
            "FROM local_album_external_identities WHERE local_album_id = 'album-1'"
        ).fetchone()
        artist_identity = connection.execute(
            "SELECT provider_artist_id, decision_source FROM "
            "local_artist_external_identities WHERE local_artist_id = 'artist-1'"
        ).fetchone()
        track_identity = connection.execute(
            "SELECT recording_mbid, release_mbid, decision_source FROM "
            "local_track_external_identities WHERE local_track_id = 'track-1'"
        ).fetchone()
        attempt_count = connection.execute(
            "SELECT COUNT(*) FROM library_identification_attempts "
            "WHERE trigger = 'contribution_submission'"
        ).fetchone()[0]
        evidence_count = connection.execute(
            "SELECT COUNT(*) FROM library_identification_evidence"
        ).fetchone()[0]
        job_state = connection.execute(
            "SELECT state FROM library_contribution_verification_jobs"
        ).fetchone()[0]
    assert album_identity[:3] == (
        _GROUP_MBID,
        _RELEASE_MBID,
        "manual",
    )
    assert album_identity[3] is not None
    assert artist_identity == (_ARTIST_MBID, "manual")
    assert track_identity == (
        _RECORDING_MBID,
        _RELEASE_MBID,
        "manual",
    )
    assert attempt_count == 1
    assert evidence_count == 1
    assert job_state == "succeeded"


@pytest.mark.asyncio
async def test_attachment_keeps_playlist_history_favorite_and_compat_local_ids(
    tmp_path,
) -> None:
    service, musicbrainz, path, _contribution_id = await _returned_contribution(
        tmp_path
    )
    with sqlite3.connect(path) as connection:
        connection.executemany(
            "INSERT INTO library_user_favorites "
            "(user_id, item_kind, item_id, created_at) VALUES (?, ?, ?, 1)",
            [
                ("curator-1", "artist", "artist-1"),
                ("curator-1", "album", "album-1"),
                ("curator-1", "track", "track-1"),
            ],
        )
        connection.execute(
            "INSERT INTO library_play_history "
            "(id, user_id, local_track_id, local_album_id, local_artist_id, "
            "track_name, artist_name, album_name, played_at) VALUES "
            "('history-1', 'curator-1', 'track-1', 'album-1', 'artist-1', "
            "'Track', 'Artist', 'Album', '2026-07-21T12:00:00Z')"
        )
        connection.execute(
            "INSERT INTO library_playlists "
            "(id, name, created_at, updated_at, user_id) VALUES "
            "('playlist-1', 'Saved', '2026-07-21', '2026-07-21', 'curator-1')"
        )
        connection.execute(
            "INSERT INTO library_playlist_tracks "
            "(id, playlist_id, position, track_name, artist_name, album_name, "
            "source_type, created_at, local_track_id, local_album_id, local_artist_id) "
            "VALUES ('playlist-track-1', 'playlist-1', 0, 'Track', 'Artist', "
            "'Album', 'local', '2026-07-21', 'track-1', 'album-1', 'artist-1')"
        )
        connection.executemany(
            "INSERT INTO library_compat_id_map (jf_id, kind, internal_id) VALUES (?, ?, ?)",
            [
                ("jf-artist", "artist", "artist-1"),
                ("jf-album", "album", "album-1"),
                ("jf-track", "track", "track-1"),
            ],
        )
        before = {
            "favorites": connection.execute(
                "SELECT user_id, item_kind, item_id FROM library_user_favorites ORDER BY item_kind"
            ).fetchall(),
            "history": connection.execute(
                "SELECT local_track_id, local_album_id, local_artist_id "
                "FROM library_play_history"
            ).fetchall(),
            "playlist": connection.execute(
                "SELECT local_track_id, local_album_id, local_artist_id "
                "FROM library_playlist_tracks"
            ).fetchall(),
            "compat": connection.execute(
                "SELECT jf_id, kind, internal_id FROM library_compat_id_map ORDER BY kind"
            ).fetchall(),
        }

    worker = LibraryContributionVerificationWorker(service._store, service, musicbrainz)
    assert await worker.run_once("worker-1", now=time.time() + 1) == "linked"

    with sqlite3.connect(path) as connection:
        after = {
            "favorites": connection.execute(
                "SELECT user_id, item_kind, item_id FROM library_user_favorites ORDER BY item_kind"
            ).fetchall(),
            "history": connection.execute(
                "SELECT local_track_id, local_album_id, local_artist_id "
                "FROM library_play_history"
            ).fetchall(),
            "playlist": connection.execute(
                "SELECT local_track_id, local_album_id, local_artist_id "
                "FROM library_playlist_tracks"
            ).fetchall(),
            "compat": connection.execute(
                "SELECT jf_id, kind, internal_id FROM library_compat_id_map ORDER BY kind"
            ).fetchall(),
        }
    assert after == before


@pytest.mark.asyncio
async def test_new_release_absence_is_retried_without_attaching(tmp_path) -> None:
    service, musicbrainz, path, _contribution_id = await _returned_contribution(
        tmp_path
    )
    musicbrainz.get_release_for_verification.return_value = None
    worker = LibraryContributionVerificationWorker(service._store, service, musicbrainz)
    now = time.time() + 1

    assert await worker.run_once("worker-1", now=now) == "retry_scheduled"

    with sqlite3.connect(path) as connection:
        job = connection.execute(
            "SELECT state, not_before, last_failure_code FROM "
            "library_contribution_verification_jobs"
        ).fetchone()
        identity_count = connection.execute(
            "SELECT COUNT(*) FROM local_album_external_identities"
        ).fetchone()[0]
    assert job[0] == "queued"
    assert job[1] > now
    assert job[2] == "MUSICBRAINZ_RELEASE_NOT_PROPAGATED"
    assert identity_count == 0


@pytest.mark.asyncio
async def test_musicbrainz_outage_returns_job_to_durable_retry(tmp_path) -> None:
    service, musicbrainz, path, _contribution_id = await _returned_contribution(
        tmp_path
    )
    musicbrainz.get_release_for_verification.side_effect = ExternalServiceError(
        "temporarily unavailable"
    )
    worker = LibraryContributionVerificationWorker(service._store, service, musicbrainz)
    now = time.time() + 1

    assert await worker.run_once("worker-1", now=now) == "retry_scheduled"

    with sqlite3.connect(path) as connection:
        job = connection.execute(
            "SELECT state, last_failure_code FROM library_contribution_verification_jobs"
        ).fetchone()
    assert job == ("queued", "MUSICBRAINZ_TEMPORARILY_UNAVAILABLE")


@pytest.mark.asyncio
async def test_bounded_propagation_failure_preserves_mbid_for_manual_retry(
    tmp_path,
) -> None:
    service, musicbrainz, path, contribution_id = await _returned_contribution(tmp_path)
    musicbrainz.get_release_for_verification.return_value = None
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_verification_jobs SET attempt_count = 10"
        )
    worker = LibraryContributionVerificationWorker(service._store, service, musicbrainz)

    assert await worker.run_once("worker-1", now=time.time() + 1) == "needs_review"
    review = await service.get(contribution_id)

    assert review.state == "needs_review"
    assert review.result_release_mbid == _RELEASE_MBID
    assert review.next_actions == ["retry_verification", "cancel"]
    with sqlite3.connect(path) as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM local_album_external_identities"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT state FROM library_contribution_verification_jobs"
            ).fetchone()[0]
            == "needs_review"
        )


@pytest.mark.asyncio
async def test_authenticated_recovery_can_replace_a_rejected_result(tmp_path) -> None:
    service, musicbrainz, _path, contribution_id = await _returned_contribution(
        tmp_path
    )
    musicbrainz.get_release_for_verification.return_value = None
    with sqlite3.connect(_path) as connection:
        connection.execute(
            "UPDATE library_contribution_verification_jobs SET attempt_count = 10"
        )
    worker = LibraryContributionVerificationWorker(service._store, service, musicbrainz)
    assert await worker.run_once("worker-1", now=time.time() + 1) == "needs_review"
    review = await service.get(contribution_id)
    replacement = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"

    verifying = await service.record_manual_result(
        contribution_id,
        release_id_or_url=replacement,
        expected_row_revision=review.row_revision,
        actor_user_id="curator-1",
        replace_existing_result=True,
    )

    assert verifying.state == "verifying"
    assert verifying.result_release_mbid == replacement
    assert verifying.result_source == "manual"


@pytest.mark.asyncio
async def test_recovery_runs_bounded_retention_cleanup_hourly() -> None:
    store = AsyncMock()
    store.recover_library_contribution_verification_leases.return_value = 0
    contributions = AsyncMock()
    worker = LibraryContributionVerificationWorker(store, contributions, AsyncMock())

    await worker.recover(now=100)
    await worker.recover(now=101)
    await worker.recover(now=3_700)

    assert store.recover_library_contribution_verification_leases.await_count == 3
    assert contributions.purge_expired_provider_data.await_count == 2
    assert store.clean_library_contribution_records.await_count == 2

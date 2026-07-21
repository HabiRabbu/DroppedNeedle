import sqlite3
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from core.exceptions import ContributionDataError, ContributionStateError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.library_contribution_service import LibraryContributionService


def _service(tmp_path: Path) -> tuple[LibraryContributionService, Path]:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        connection.execute("INSERT INTO auth_users(id) VALUES ('curator-1')")
    store = NativeLibraryStore(path, threading.Lock())
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, kind, created_at, updated_at) "
            "VALUES ('artist-1', 'Artist', 'artist', 'person', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, year, grouping_source, created_at, updated_at) "
            "VALUES ('album-1', 'root-1', 'group-1', 'Album', 'album', 'Artist', "
            "'artist', 'artist-1', 2001, 'automatic', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_tracks "
            "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
            "file_size_bytes, file_mtime_ns, stat_revision, tag_revision, title, "
            "title_folded, artist_name, artist_name_folded, album_title, "
            "album_title_folded, album_artist_name, album_artist_name_folded, "
            "disc_number, track_number, duration_seconds, file_format, availability, "
            "ingest_source, imported_at, membership_source) "
            "VALUES ('track-1', 'album-1', 'root-1', '/private/music/track.flac', "
            "'track.flac', 'hash-1', 100, 200, 'stat-1', 'tag-1', 'Track', 'track', "
            "'Artist', 'artist', 'Album', 'album', 'Artist', 'artist', 1, 1, 180, "
            "'flac', 'indexed', 'scan', 1, 'automatic')"
        )
    return LibraryContributionService(store), path


@pytest.mark.asyncio
async def test_local_snapshot_is_safe_and_draft_edits_do_not_touch_catalog_or_files(
    tmp_path: Path,
) -> None:
    service, path = _service(tmp_path)
    contribution = await service.create("album-1", "curator-1")

    encoded = str(contribution.local_snapshot)
    assert "/private" not in encoded
    assert "track.flac" not in encoded
    assert contribution.local_snapshot.title == "Album"
    assert contribution.local_snapshot.media[0].tracks[0].title == "Track"

    contribution.draft.title.value = "Corrected album"
    contribution.draft.title.source = "entered_here"
    updated = await service.update(
        contribution.id,
        expected_row_revision=contribution.row_revision,
        draft=contribution.draft,
        actor_user_id="curator-1",
    )
    assert updated.draft.title.value == "Corrected album"
    assert updated.draft.title.source == "entered_here"

    with sqlite3.connect(path) as connection:
        album_title = connection.execute(
            "SELECT title FROM local_albums WHERE id = 'album-1'"
        ).fetchone()[0]
        file_path = connection.execute(
            "SELECT file_path FROM local_tracks WHERE id = 'track-1'"
        ).fetchone()[0]
    assert album_title == "Album"
    assert file_path == "/private/music/track.flac"


@pytest.mark.asyncio
async def test_exact_musicbrainz_release_cannot_start_a_contribution(
    tmp_path: Path,
) -> None:
    service, path = _service(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO local_album_external_identities "
            "(local_album_id, provider, release_group_mbid, release_mbid, "
            "decision_source, selected_at) VALUES "
            "('album-1', 'musicbrainz', 'group-1', 'release-1', 'manual', 2)"
        )

    with pytest.raises(ContributionStateError, match="already has an exact"):
        await service.create("album-1", "curator-1")


@pytest.mark.parametrize(
    ("artist_kind", "artist_name", "expected_code"),
    [
        ("unknown", "Unknown Artist", "ARTIST_CREDIT_PLACEHOLDER"),
        ("various_artists", "Various Artists", "VARIOUS_ARTISTS_IDENTITY_REQUIRED"),
    ],
)
@pytest.mark.asyncio
async def test_placeholder_artist_kinds_are_blocked_from_musicbrainz_seed_drafts(
    tmp_path: Path,
    artist_kind: str,
    artist_name: str,
    expected_code: str,
) -> None:
    service, path = _service(tmp_path)
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE local_artists SET display_name = ?, kind = ? WHERE id = 'artist-1'",
            (artist_name, artist_kind),
        )
        connection.execute(
            "UPDATE local_albums SET album_artist_name = ? WHERE id = 'album-1'",
            (artist_name,),
        )

    contribution = await service.create("album-1", "curator-1")

    assert expected_code in {issue.code for issue in contribution.validation}


@pytest.mark.asyncio
async def test_provider_cleanup_skips_a_malformed_row_and_continues() -> None:
    store = AsyncMock()
    store.list_library_contributions_for_provider_purge.return_value = [
        {"id": "broken"},
        {"id": "valid"},
    ]
    service = LibraryContributionService(store)
    service._purge_provider_data_row = AsyncMock(
        side_effect=[ContributionDataError("bad document"), True]
    )

    assert await service.purge_expired_provider_data(now=10) == 1
    assert service._purge_provider_data_row.await_count == 2


@pytest.mark.asyncio
async def test_changed_input_becomes_stale_and_rebuild_creates_a_new_audit_row(
    tmp_path: Path,
) -> None:
    service, path = _service(tmp_path)
    contribution = await service.create("album-1", "curator-1")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE local_tracks SET tag_revision = 'tag-2', title = 'Changed' "
            "WHERE id = 'track-1'"
        )

    stale = await service.get(contribution.id)
    assert stale.state == "stale"
    rebuilt = await service.rebuild(
        stale.id,
        expected_row_revision=stale.row_revision,
        actor_user_id="curator-1",
    )
    assert rebuilt.id != stale.id
    assert rebuilt.local_snapshot.media[0].tracks[0].title == "Changed"
    assert rebuilt.state == "draft"


@pytest.mark.parametrize(
    ("state", "expected"),
    [
        ("draft", "stale"),
        ("ready", "stale"),
        ("seeded", "stale"),
        ("verifying", "stale"),
        ("needs_review", "stale"),
        ("linked", "linked"),
        ("cancelled", "cancelled"),
        ("stale", "stale"),
    ],
)
@pytest.mark.asyncio
async def test_missing_final_track_closes_every_open_contribution_state(
    tmp_path: Path, state: str, expected: str
) -> None:
    service, path = _service(tmp_path)
    contribution = await service.create("album-1", "curator-1")
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = ? WHERE id = ?",
            (state, contribution.id),
        )
        connection.execute(
            "UPDATE local_tracks SET availability = 'missing', missing_since = 3 "
            "WHERE id = 'track-1'"
        )

    retained = await service.get(contribution.id)

    assert retained.state == expected

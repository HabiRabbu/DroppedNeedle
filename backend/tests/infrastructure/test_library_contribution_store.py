import asyncio
import sqlite3
import threading
from pathlib import Path

import pytest

from core.exceptions import ResourceNotFoundError, StaleRevisionError, ValidationError
from infrastructure.persistence.native_library_store import NativeLibraryStore


def _store_with_album(tmp_path: Path) -> tuple[NativeLibraryStore, Path]:
    path = tmp_path / "library.db"
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
        connection.executemany(
            "INSERT INTO auth_users(id) VALUES (?)", [("curator-1",), ("curator-2",)]
        )
    store = NativeLibraryStore(path, threading.Lock())
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, kind, created_at, updated_at) "
            "VALUES ('artist-1', 'Artist', 'artist', 'person', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, grouping_source, created_at, updated_at) "
            "VALUES ('album-1', 'root-1', 'group-1', 'Album', 'album', 'Artist', "
            "'artist', 'artist-1', 'automatic', 1, 1)"
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
    return store, path


@pytest.mark.asyncio
async def test_contribution_schema_is_idempotent_and_enforces_subjects(
    tmp_path: Path,
) -> None:
    store, path = _store_with_album(tmp_path)
    NativeLibraryStore(path, store._write_lock)

    assert {
        "local_entity_source_links",
        "library_contribution_drafts",
        "library_contribution_callback_tokens",
        "library_contribution_verification_jobs",
    }.issubset(await store.table_names())

    with pytest.raises(ValidationError):
        await store.upsert_local_entity_source_link(
            local_artist_id="artist-1",
            local_album_id="album-1",
            local_track_id=None,
            provider="discogs",
            external_entity_type="release",
            external_id="123",
            canonical_url="https://www.discogs.com/release/123",
            decision_source="curator_selected",
            selected_by_user_id="curator-1",
            verified_at=2,
            now=2,
        )


@pytest.mark.asyncio
async def test_create_is_atomic_per_album_and_edits_use_optimistic_revision(
    tmp_path: Path,
) -> None:
    store, _path = _store_with_album(tmp_path)
    context = await store.get_album_identification_context("album-1")
    assert context is not None
    tracks = [
        track for track in context["tracks"] if track["availability"] == "indexed"
    ]
    from services.native.identification_revisions import album_input_revisions

    input_revision = ":".join(album_input_revisions(tracks))

    async def create(actor: str):
        return await store.create_or_get_library_contribution(
            local_album_id="album-1",
            actor_user_id=actor,
            album_row_revision=1,
            input_revision=input_revision,
            local_snapshot_json='{"schema_version":1}',
            resolved_draft_json='{"schema_version":1}',
            source_selection_json='{"schema_version":1}',
            now=2,
        )

    first, second = await asyncio.gather(create("curator-1"), create("curator-2"))
    assert first["id"] == second["id"]
    assert await store.row_count("library_contribution_drafts") == 1

    updated = await store.update_library_contribution_draft(
        contribution_id=str(first["id"]),
        expected_row_revision=1,
        actor_user_id="curator-2",
        resolved_draft_json='{"schema_version":1,"title":"changed"}',
        state="ready",
        now=3,
    )
    assert updated["row_revision"] == 2
    assert updated["updated_by_user_id"] == "curator-2"

    with pytest.raises(StaleRevisionError):
        await store.update_library_contribution_draft(
            contribution_id=str(first["id"]),
            expected_row_revision=1,
            actor_user_id="curator-1",
            resolved_draft_json='{"schema_version":1}',
            state="draft",
            now=4,
        )


@pytest.mark.asyncio
async def test_missing_final_track_removes_active_contribution_from_album_lookup(
    tmp_path: Path,
) -> None:
    store, path = _store_with_album(tmp_path)
    context = await store.get_album_identification_context("album-1")
    assert context is not None
    from services.native.identification_revisions import album_input_revisions

    revision = ":".join(album_input_revisions(context["tracks"]))
    contribution = await store.create_or_get_library_contribution(
        local_album_id="album-1",
        actor_user_id="curator-1",
        album_row_revision=1,
        input_revision=revision,
        local_snapshot_json='{"schema_version":1}',
        resolved_draft_json='{"schema_version":1}',
        source_selection_json='{"schema_version":1}',
        now=2,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE local_tracks SET availability = 'missing', missing_since = 3 "
            "WHERE id = 'track-1'"
        )

    assert await store.get_active_album_contribution("album-1") is None
    retained = await store.get_library_contribution(str(contribution["id"]))
    assert retained is not None
    assert retained["album_active"] is False


@pytest.mark.asyncio
async def test_callback_is_one_time_and_verification_leases_are_restart_safe(
    tmp_path: Path,
) -> None:
    store, path = _store_with_album(tmp_path)
    context = await store.get_album_identification_context("album-1")
    assert context is not None
    from services.native.identification_revisions import album_input_revisions

    revision = ":".join(album_input_revisions(context["tracks"]))
    contribution = await store.create_or_get_library_contribution(
        local_album_id="album-1",
        actor_user_id="curator-1",
        album_row_revision=1,
        input_revision=revision,
        local_snapshot_json='{"schema_version":1}',
        resolved_draft_json='{"schema_version":1}',
        source_selection_json='{"schema_version":1}',
        now=2,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'ready' WHERE id = ?",
            (contribution["id"],),
        )
    await store.issue_library_contribution_callback_token(
        token_hash="hash-1",
        contribution_id=str(contribution["id"]),
        requested_by_user_id="curator-1",
        expires_at=100,
        now=3,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'seeded' WHERE id = ?",
            (contribution["id"],),
        )

    contribution_id, job_id = await store.consume_library_contribution_callback_token(
        token_hash="hash-1", release_mbid="release-1", now=4
    )
    assert contribution_id == contribution["id"]
    assert job_id is not None
    with pytest.raises(ResourceNotFoundError, match="invalid or expired"):
        await store.consume_library_contribution_callback_token(
            token_hash="hash-1", release_mbid="release-1", now=5
        )

    claimed = await store.claim_library_contribution_verification(
        worker_id="worker-1", now=4, lease_seconds=10
    )
    assert claimed is not None
    assert claimed["id"] == job_id
    heartbeat_revision = await store.heartbeat_library_contribution_verification(
        job_id=job_id,
        worker_id="worker-1",
        expected_row_revision=int(claimed["row_revision"]),
        now=5,
        lease_seconds=10,
    )
    await store.retry_library_contribution_verification(
        job_id=job_id,
        worker_id="worker-1",
        expected_row_revision=heartbeat_revision,
        failure_code="UPSTREAM_PROPAGATING",
        not_before=20,
        now=6,
    )
    assert (
        await store.claim_library_contribution_verification(
            worker_id="worker-2", now=19, lease_seconds=10
        )
        is None
    )
    reclaimed = await store.claim_library_contribution_verification(
        worker_id="worker-2", now=20, lease_seconds=10
    )
    assert reclaimed is not None
    assert reclaimed["attempt_count"] == 2


@pytest.mark.asyncio
async def test_stale_callback_records_result_without_queuing_attachment(
    tmp_path: Path,
) -> None:
    store, path = _store_with_album(tmp_path)
    context = await store.get_album_identification_context("album-1")
    assert context is not None
    from services.native.identification_revisions import album_input_revisions

    revision = ":".join(album_input_revisions(context["tracks"]))
    contribution = await store.create_or_get_library_contribution(
        local_album_id="album-1",
        actor_user_id="curator-1",
        album_row_revision=1,
        input_revision=revision,
        local_snapshot_json='{"schema_version":1}',
        resolved_draft_json='{"schema_version":1}',
        source_selection_json='{"schema_version":1}',
        now=2,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'ready' WHERE id = ?",
            (contribution["id"],),
        )
    await store.issue_library_contribution_callback_token(
        token_hash="stale-hash",
        contribution_id=str(contribution["id"]),
        requested_by_user_id="curator-1",
        expires_at=100,
        now=3,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'stale' WHERE id = ?",
            (contribution["id"],),
        )
        connection.execute(
            "UPDATE local_tracks SET availability = 'missing' WHERE id = 'track-1'"
        )

    contribution_id, job_id = await store.consume_library_contribution_callback_token(
        token_hash="stale-hash", release_mbid="release-returned", now=4
    )

    assert contribution_id == contribution["id"]
    assert job_id is None
    with sqlite3.connect(path) as connection:
        retained = connection.execute(
            "SELECT state, result_release_mbid, result_source "
            "FROM library_contribution_drafts WHERE id = ?",
            (contribution["id"],),
        ).fetchone()
        job_count = connection.execute(
            "SELECT COUNT(*) FROM library_contribution_verification_jobs"
        ).fetchone()[0]
    assert retained == ("stale", "release-returned", "callback")
    assert job_count == 0


@pytest.mark.asyncio
async def test_manual_result_consumes_outstanding_callback_tokens(
    tmp_path: Path,
) -> None:
    store, path = _store_with_album(tmp_path)
    context = await store.get_album_identification_context("album-1")
    assert context is not None
    from services.native.identification_revisions import album_input_revisions

    revision = ":".join(album_input_revisions(context["tracks"]))
    contribution = await store.create_or_get_library_contribution(
        local_album_id="album-1",
        actor_user_id="curator-1",
        album_row_revision=1,
        input_revision=revision,
        local_snapshot_json='{"schema_version":1}',
        resolved_draft_json='{"schema_version":1}',
        source_selection_json='{"schema_version":1}',
        now=2,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'ready' WHERE id = ?",
            (contribution["id"],),
        )
    await store.issue_library_contribution_callback_token(
        token_hash="manual-hash",
        contribution_id=str(contribution["id"]),
        requested_by_user_id="curator-1",
        expires_at=100,
        now=3,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'seeded' WHERE id = ?",
            (contribution["id"],),
        )

    await store.record_library_contribution_manual_result(
        contribution_id=str(contribution["id"]),
        release_mbid="manual-release",
        expected_row_revision=1,
        actor_user_id="curator-1",
        replace_existing_result=False,
        now=4,
    )

    with pytest.raises(ResourceNotFoundError, match="invalid or expired"):
        await store.consume_library_contribution_callback_token(
            token_hash="manual-hash", release_mbid="delayed-release", now=5
        )


@pytest.mark.asyncio
async def test_cleanup_purges_expired_seed_snapshot_without_removing_audit_row(
    tmp_path: Path,
) -> None:
    store, path = _store_with_album(tmp_path)
    context = await store.get_album_identification_context("album-1")
    assert context is not None
    from services.native.identification_revisions import album_input_revisions

    revision = ":".join(album_input_revisions(context["tracks"]))
    contribution = await store.create_or_get_library_contribution(
        local_album_id="album-1",
        actor_user_id="curator-1",
        album_row_revision=1,
        input_revision=revision,
        local_snapshot_json='{"schema_version":1}',
        resolved_draft_json='{"schema_version":1}',
        source_selection_json='{"schema_version":1}',
        now=1,
    )
    with sqlite3.connect(path) as connection:
        connection.execute(
            "UPDATE library_contribution_drafts SET state = 'seeded', "
            'seed_snapshot_json = \'{"private":"temporary"}\', seeded_at = 2 '
            "WHERE id = ?",
            (contribution["id"],),
        )
        connection.execute(
            "INSERT INTO library_contribution_callback_tokens "
            "(token_hash, contribution_id, requested_by_user_id, expires_at, created_at) "
            "VALUES ('expired-seed', ?, 'curator-1', 100, 2)",
            (contribution["id"],),
        )

    before_expiry = await store.clean_library_contribution_records(now=100)
    result = await store.clean_library_contribution_records(now=101)

    assert before_expiry["seed_snapshots"] == 0
    assert result["seed_snapshots"] == 1
    with sqlite3.connect(path) as connection:
        retained = connection.execute(
            "SELECT state, seed_snapshot_json FROM library_contribution_drafts WHERE id = ?",
            (contribution["id"],),
        ).fetchone()
    assert retained == ("seeded", None)

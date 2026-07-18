import sqlite3
import threading
from pathlib import Path

import pytest

from api.v1.schemas.library_policies import LibraryRootSettings, TypedLibrarySettings
from core.exceptions import StaleRevisionError
from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.bounded_legacy_catalog_migrator import (
    BoundedLegacyCatalogMigrator,
)
from services.native.library_policy_resolver import LibraryPolicyResolver
from tests.infrastructure.test_legacy_catalog_importer import (
    RG,
    TRACK_1,
    _create_source,
)


def _migrator(
    database: Path,
    root: Path,
    progress: list[str],
    *,
    batch_size: int = 1,
) -> tuple[NativeLibraryStore, BoundedLegacyCatalogMigrator]:
    store = NativeLibraryStore(database, threading.Lock())
    resolver = LibraryPolicyResolver(
        TypedLibrarySettings(
            library_roots=[
                LibraryRootSettings(
                    id="root-1",
                    path=str(root),
                    label="Music",
                    policy="automatic",
                )
            ]
        )
    )
    return store, BoundedLegacyCatalogMigrator(
        store,
        resolver,
        emit_progress=progress.append,
        batch_size=batch_size,
    )


@pytest.mark.asyncio
async def test_bounded_migration_indexes_review_path_resolution(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    store, _migrator_instance = _migrator(database, root, [])

    await store.prepare_bounded_legacy_migration()

    with sqlite3.connect(database) as connection:
        plan = connection.execute(
            "EXPLAIN QUERY PLAN SELECT id FROM local_tracks WHERE file_path = ?",
            (str(root / "Compilation" / "01.flac"),),
        ).fetchall()
    assert any("idx_bounded_migration_local_track_path" in str(row) for row in plan)

    await store.finish_bounded_legacy_migration()


@pytest.mark.asyncio
async def test_bounded_migration_preserves_catalog_references_and_reports_progress(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    progress: list[str] = []
    store, migrator = _migrator(database, root, progress)

    outcome = await migrator.migrate("bounded-migration", now=100)

    assert outcome.blocker_count == 0
    assert outcome.report.state == "applied"
    assert (outcome.report.identified_albums, outcome.report.identified_tracks) == (
        1,
        2,
    )
    assert (outcome.report.local_only_albums, outcome.report.local_only_tracks) == (
        2,
        2,
    )
    assert outcome.invariants == {
        "foreign_key_violations": 0,
        "orphan_tracks": 0,
        "duplicate_paths": 0,
        "unresolved_provenance": 0,
        "unresolved_references": 0,
    }
    assert await store.row_count("local_tracks") == 4
    assert await store.row_count("library_user_favorites") == 3
    assert await store.row_count("library_play_history") == 1
    assert await store.row_count("library_playlist_tracks") == 2
    assert await store.row_count("library_album_release_pins") == 1
    assert await store.row_count("library_compat_bookmarks") == 1
    assert await store.row_count("library_compat_play_queue_items") == 2
    assert await store.row_count("library_compat_id_map") == 3
    assert await store.row_count("library_reference_tombstones") == 1
    assert await store.resolve_migrated_reference("favorite", f"alice:album:{RG}") == (
        "local_album",
        await store.resolve_album_alias(RG),
    )
    assert await store.resolve_migrated_reference(
        "compat_bookmark", f"alice:{TRACK_1}"
    ) == ("local_track", TRACK_1)
    assert progress[0] == "[upgrade] Migrating catalog tracks: 0/2 (0%)."
    assert "[upgrade] Migrating catalog tracks: 2/2 (100%)." in progress
    assert progress[-1].endswith("14/14 (100%).")
    with sqlite3.connect(database) as connection:
        temporary_objects = connection.execute(
            "SELECT name FROM sqlite_master WHERE name IN "
            "('idx_bounded_legacy_library_files', "
            "'idx_bounded_migration_local_track_path', "
            "'library_migration_review_staging')"
        ).fetchall()
    assert temporary_objects == []


@pytest.mark.asyncio
async def test_bounded_migration_retains_provider_era_and_removed_jellyfin_references(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO play_history VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "provider-era-history",
                "alice",
                "First",
                "Artist One",
                "Compilation",
                None,
                None,
                180000,
                None,
                "2025-01-01T00:00:00Z",
            ),
        )
        connection.execute(
            "INSERT INTO playlist_tracks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                "provider-era-playlist-track",
                "playlist-1",
                2,
                "Unavailable provider track",
                "Former Artist",
                "Former Album",
                None,
                None,
                None,
                None,
                "",
                "[]",
                None,
                None,
                None,
                None,
                "c",
                None,
                None,
            ),
        )
        connection.executemany(
            "INSERT INTO compat_id_map VALUES (?, ?, ?)",
            [
                ("d" * 32, "library", "music"),
                ("e" * 32, "track", "removed-track"),
                ("f" * 32, "genre", "Electronic"),
                ("g" * 32, "playlist", "playlist-1"),
                ("h" * 32, "playlist", "removed-playlist"),
            ],
        )
    store, migrator = _migrator(database, root, [])

    outcome = await migrator.migrate("bounded-provider-era", now=100)

    assert outcome.blocker_count == 0
    with sqlite3.connect(database) as connection:
        history = connection.execute(
            "SELECT local_track_id FROM library_play_history WHERE id = ?",
            ("provider-era-history",),
        ).fetchone()
        mappings = connection.execute(
            "SELECT jf_id, kind, internal_id FROM library_compat_id_map "
            "WHERE jf_id IN (?, ?, ?, ?, ?) ORDER BY jf_id",
            ("d" * 32, "e" * 32, "f" * 32, "g" * 32, "h" * 32),
        ).fetchall()
    assert history == (TRACK_1,)
    assert mappings == [
        ("d" * 32, "library", "music"),
        ("e" * 32, "track", "removed-track"),
        ("f" * 32, "genre", "Electronic"),
        ("g" * 32, "playlist", "playlist-1"),
        ("h" * 32, "playlist", "removed-playlist"),
    ]
    counts = {
        count.kind: count
        for count in outcome.report.reference_counts
        if count.user_id is None
    }
    assert counts["history"].source == counts["history"].mapped == 2
    assert counts["playlist_track"].tombstoned == 2
    assert counts["jellyfin_id_map"].tombstoned == 2


@pytest.mark.asyncio
async def test_bounded_migration_blocks_ambiguous_history_without_completion_marker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE library_files SET track_title = 'First', artist_name = 'Artist One' "
            "WHERE id != ?",
            (TRACK_1,),
        )
        connection.execute(
            "INSERT INTO play_history VALUES (?,?,?,?,?,?,?,?,?,?)",
            (
                "ambiguous-history",
                "alice",
                "First",
                "Artist One",
                "Compilation",
                None,
                None,
                180000,
                None,
                "2025-01-01T00:00:00Z",
            ),
        )
    store, migrator = _migrator(database, root, [])

    outcome = await migrator.migrate("bounded-blocked", now=100)

    assert outcome.report.state == "blocked"
    assert outcome.blocker_count == 1
    assert any("ambiguous-history" in blocker for blocker in outcome.report.blockers)
    assert await store.row_count("library_migration_markers") == 0


@pytest.mark.asyncio
async def test_bounded_migration_is_idempotent(tmp_path: Path) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    with sqlite3.connect(database) as connection:
        connection.execute("DELETE FROM library_album_meta")
        connection.execute("UPDATE library_albums SET cover_url = NULL")
    store, first = _migrator(database, root, [], batch_size=2)

    initial = await first.migrate("bounded-repeat", now=100)
    counts = {
        table: await store.row_count(table)
        for table in (
            "local_albums",
            "local_tracks",
            "library_migration_provenance",
            "library_reference_tombstones",
        )
    }
    revision = await store.get_catalog_revision()
    _, second = _migrator(database, root, [], batch_size=1)

    repeated = await second.migrate("bounded-repeat", now=101)

    assert initial.report.state == repeated.report.state == "applied"
    assert initial.report == repeated.report
    assert {table: await store.row_count(table) for table in counts} == counts
    assert await store.get_catalog_revision() == revision
    with sqlite3.connect(database) as connection:
        artwork = connection.execute(
            "SELECT cover_url, source, source_locator FROM local_album_artwork "
            "WHERE local_album_id = ?",
            (await store.resolve_album_alias(RG),),
        ).fetchone()
    assert artwork == (None, "provider", RG)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE library_files SET track_title = 'Changed' WHERE id = ?",
            (TRACK_1,),
        )
    _, changed = _migrator(database, root, [], batch_size=1)
    with pytest.raises(StaleRevisionError, match="migration input"):
        await changed.migrate("bounded-repeat", now=102)


@pytest.mark.asyncio
async def test_bounded_migration_resumes_after_a_committed_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    store, interrupted = _migrator(database, root, [], batch_size=1)
    apply_bundle = store.apply_legacy_catalog_bundle
    calls = 0

    async def apply_then_interrupt(*args, **kwargs):
        nonlocal calls
        applied = await apply_bundle(*args, **kwargs)
        calls += 1
        if calls == 1:
            raise RuntimeError("simulated process interruption")
        return applied

    monkeypatch.setattr(store, "apply_legacy_catalog_bundle", apply_then_interrupt)
    with pytest.raises(RuntimeError, match="simulated process interruption"):
        await interrupted.migrate("bounded-resume", now=100)

    _, resumed = _migrator(database, root, [], batch_size=1)
    outcome = await resumed.migrate("bounded-resume", now=101)

    assert outcome.report.state == "applied"
    assert outcome.blocker_count == 0
    assert await store.row_count("local_tracks") == 4
    assert await store.row_count("library_migration_markers") == 1


@pytest.mark.asyncio
async def test_bounded_migration_resumes_after_a_committed_review_album(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    store, interrupted = _migrator(database, root, [], batch_size=1)
    apply_bundle = store.apply_legacy_catalog_bundle
    interrupted_review = False

    async def apply_then_interrupt(*args, **kwargs):
        nonlocal interrupted_review
        applied = await apply_bundle(*args, **kwargs)
        bundle = args[0]
        if bundle.album_identity is None and not interrupted_review:
            interrupted_review = True
            raise RuntimeError("simulated review interruption")
        return applied

    monkeypatch.setattr(store, "apply_legacy_catalog_bundle", apply_then_interrupt)
    with pytest.raises(RuntimeError, match="simulated review interruption"):
        await interrupted.migrate("bounded-review-resume", now=100)

    _, resumed = _migrator(database, root, [], batch_size=1)
    outcome = await resumed.migrate("bounded-review-resume", now=101)

    assert outcome.report.state == "applied"
    assert outcome.blocker_count == 0
    assert (outcome.report.local_only_albums, outcome.report.local_only_tracks) == (
        2,
        2,
    )
    assert await store.row_count("local_tracks") == 4
    assert await store.row_count("library_migration_markers") == 1


@pytest.mark.asyncio
async def test_bounded_migration_chunks_tracks_within_one_review_album(
    tmp_path: Path,
) -> None:
    root = tmp_path / "Music"
    root.mkdir()
    database = tmp_path / "library.db"
    _create_source(database, root)
    second_local_track = root / "Local Album" / "02.flac"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "INSERT INTO manual_review_queue VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                5,
                str(second_local_track),
                "Another Local Song",
                "Local Artist",
                "Local Album",
                2025,
                2,
                1,
                "flac",
                195.0,
                310,
                None,
                None,
                "[]",
                "text_match",
                12.5,
                None,
                None,
            ),
        )
    store, migrator = _migrator(database, root, [], batch_size=1)

    outcome = await migrator.migrate("bounded-review-chunks", now=100)

    assert outcome.report.state == "applied"
    assert (outcome.report.local_only_albums, outcome.report.local_only_tracks) == (
        2,
        3,
    )
    assert await store.row_count("local_tracks") == 5

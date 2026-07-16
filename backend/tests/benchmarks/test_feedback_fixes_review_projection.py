"""Large review projection and named-index proof for Feedback Fixes."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.native_library_store import NativeLibraryStore
from services.native.library_review_service import LibraryReviewService

REVIEW_ROWS = 115_000


def _seed_reviews(path: Path) -> None:
    with sqlite3.connect(path) as connection:
        connection.execute("CREATE TABLE auth_users (id TEXT PRIMARY KEY)")
    NativeLibraryStore(path, threading.Lock())
    with sqlite3.connect(path) as connection:
        connection.execute("PRAGMA synchronous=OFF")
        connection.execute(
            "INSERT INTO local_artists "
            "(id, display_name, folded_name, normalized_name, kind, created_at, updated_at) "
            "VALUES ('artist', 'Artist', 'artist', 'artist', 'group', 1, 1)"
        )
        connection.execute(
            "INSERT INTO local_albums "
            "(id, root_id, grouping_key, title, title_folded, album_artist_name, "
            "album_artist_name_folded, album_artist_id, grouping_source, created_at, updated_at) "
            "VALUES ('album', 'root', 'group', 'Album', 'album', 'Artist', "
            "'artist', 'artist', 'automatic', 1, 1)"
        )
        batch_size = 2_000
        for start in range(0, REVIEW_ROWS, batch_size):
            stop = min(REVIEW_ROWS, start + batch_size)
            connection.executemany(
                "INSERT INTO local_tracks "
                "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
                "file_size_bytes, file_mtime_ns, stat_revision, title, title_folded, "
                "artist_name, artist_name_folded, album_title, album_title_folded, "
                "album_artist_name, album_artist_name_folded, file_format, ingest_source, "
                "imported_at, membership_source) "
                "VALUES (?, 'album', 'root', ?, ?, ?, 100, 1, ?, ?, ?, 'Artist', "
                "'artist', 'Album', 'album', 'Artist', 'artist', 'flac', 'scan', 1, 'automatic')",
                [
                    (
                        f"track-{index:06d}",
                        f"/music/{index:06d}.flac",
                        f"music/{index:06d}.flac",
                        f"hash-{index:06d}",
                        f"stat-{index:06d}",
                        f"Track {index}",
                        f"track {index}",
                    )
                    for index in range(start, stop)
                ],
            )
            connection.executemany(
                "INSERT INTO library_identification_reviews "
                "(id, local_track_id, state, reason_code, input_revision, created_at, updated_at) "
                "VALUES (?, ?, 'needs_review', ?, ?, ?, ?)",
                [
                    (
                        f"review-{index:06d}",
                        f"track-{index:06d}",
                        "NO_SAFE_MATCH" if index % 2 else "MISSING_METADATA",
                        f"input-{index:06d}",
                        float(index),
                        float(index),
                    )
                    for index in range(start, stop)
                ],
            )
            connection.commit()
        connection.execute("ANALYZE")


@pytest.mark.asyncio
async def test_115000_review_cursor_is_stable_and_named_indexes_cover_filters(
    tmp_path: Path,
) -> None:
    path = tmp_path / "review-benchmark.db"
    _seed_reviews(path)
    store = NativeLibraryStore(path, threading.Lock())
    service = LibraryReviewService(store)

    first = await service.list_reviews(limit=50, state="needs_review", sort="newest")
    assert len(first.items) == 50
    assert first.filtered_total == REVIEW_ROWS
    assert first.has_more is True
    assert first.next_cursor is not None

    with sqlite3.connect(path) as connection:
        connection.execute(
            "INSERT INTO local_tracks "
            "(id, local_album_id, root_id, file_path, relative_path, path_hash, "
            "file_size_bytes, file_mtime_ns, stat_revision, title, title_folded, "
            "album_title, album_title_folded, file_format, ingest_source, imported_at, "
            "membership_source) VALUES ('track-new', 'album', 'root', '/music/new.flac', "
            "'music/new.flac', 'hash-new', 100, 1, 'stat-new', 'New', 'new', 'Album', "
            "'album', 'flac', 'scan', 1, 'automatic')"
        )
        connection.execute(
            "INSERT INTO library_identification_reviews "
            "(id, local_track_id, state, reason_code, input_revision, created_at, updated_at) "
            "VALUES ('review-new', 'track-new', 'needs_review', 'NO_SAFE_MATCH', "
            "'input-new', 200000, 200000)"
        )
    second = await service.list_reviews(
        limit=50,
        state="needs_review",
        sort="newest",
        cursor=first.next_cursor,
    )
    assert "review-new" not in {item.id for item in second.items}
    assert set(item.id for item in first.items).isdisjoint(
        item.id for item in second.items
    )

    with sqlite3.connect(path) as connection:
        state_plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM library_identification_reviews "
                "WHERE state = ? AND (updated_at < ? OR (updated_at = ? AND id < ?)) "
                "ORDER BY updated_at DESC, id DESC LIMIT 51",
                ("needs_review", 100000.0, 100000.0, "review-100000"),
            )
        )
        reason_plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM library_identification_reviews "
                "WHERE reason_code = ? ORDER BY updated_at DESC, id DESC LIMIT 51",
                ("NO_SAFE_MATCH",),
            )
        )
        created_plan = " ".join(
            str(row[3])
            for row in connection.execute(
                "EXPLAIN QUERY PLAN SELECT id FROM library_identification_reviews "
                "WHERE created_at >= ? ORDER BY created_at DESC, id DESC LIMIT 51",
                (100000.0,),
            )
        )
    assert "idx_library_reviews_state_cursor" in state_plan
    assert "idx_library_reviews_reason_cursor" in reason_plan
    assert "idx_library_reviews_created_cursor" in created_plan

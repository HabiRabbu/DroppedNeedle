"""Task 011: LibraryDB native-engine schema — tables, indexes, idempotency."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.library_db import LibraryDB

_NATIVE_TABLES = {"library_files", "manual_review_queue", "library_album_meta"}
_NEW_ALBUM_COLUMNS = {
    "track_count",
    "expected_track_count",
    "total_size_bytes",
    "quality_format",
    "is_compilation",
    "source",
}


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "library.db"
    LibraryDB(db_path=path, write_lock=threading.Lock())
    return path


def _tables(path: Path) -> set[str]:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    finally:
        conn.close()


def test_native_tables_created(db_path):
    assert _NATIVE_TABLES <= _tables(db_path)


def test_library_albums_gains_scan_columns(db_path):
    conn = sqlite3.connect(db_path)
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(library_albums)")}
    finally:
        conn.close()
    assert _NEW_ALBUM_COLUMNS <= cols


def test_library_files_partial_unique_index_present(db_path):
    conn = sqlite3.connect(db_path)
    try:
        indexes = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='library_files'"
        )}
    finally:
        conn.close()
    assert "idx_library_files_active_path" in indexes


def test_manual_review_queue_unique_file_path(db_path):
    conn = sqlite3.connect(db_path)
    try:
        conn.execute(
            "INSERT INTO manual_review_queue (file_path, created_at) VALUES ('/a.flac', 1.0)"
        )
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO manual_review_queue (file_path, created_at) VALUES ('/a.flac', 2.0)"
            )
    finally:
        conn.close()


def test_library_files_check_requires_mbid_or_manual_review(db_path):
    conn = sqlite3.connect(db_path)
    try:
        # null release_group_mbid with source != 'manual_review' violates the CHECK
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO library_files "
                "(id, track_number, track_title, album_title, file_path, file_size_bytes, "
                " file_mtime, file_format, source, imported_at) "
                "VALUES ('x', 1, 't', 'al', '/x.flac', 1, 1.0, 'flac', 'scan', 1.0)"
            )
        # same row with source='manual_review' is allowed
        conn.execute(
            "INSERT INTO library_files "
            "(id, track_number, track_title, album_title, file_path, file_size_bytes, "
            " file_mtime, file_format, source, imported_at) "
            "VALUES ('y', 1, 't', 'al', '/y.flac', 1, 1.0, 'flac', 'manual_review', 1.0)"
        )
        conn.commit()
    finally:
        conn.close()


def test_reinit_is_idempotent(db_path):
    # Re-running the migration on an existing db must not raise.
    LibraryDB(db_path=db_path, write_lock=threading.Lock())
    assert _NATIVE_TABLES <= _tables(db_path)

"""Regression tests for case-insensitive release-group MBID lookups in LibraryDB.

MusicBrainz UUIDs are conventionally lowercase, and ``library_files`` stores them
lower-cased. Every ``WHERE release_group_mbid = ?`` site must normalize its input
or a mixed-case MBID silently returns no rows - which surfaced as "Request this
track" buttons appearing on every track of an in-library album (the album header
uses a separate, case-insensitive check).
"""

import threading
from pathlib import Path

import pytest

from infrastructure.persistence.library_db import LibraryDB


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(db_path=tmp_path / "test.db", write_lock=threading.Lock())


def _file_row(rg_mbid: str, *, file_path: str, track_number: int = 1) -> dict:
    """Minimal library_files row with only the columns the lookup cares about."""
    return {
        "release_group_mbid": rg_mbid,
        "release_mbid": None,
        "recording_mbid": None,
        "disc_number": 1,
        "track_number": track_number,
        "track_title": f"Track {track_number}",
        "artist_name": "Artist",
        "artist_mbid": None,
        "album_artist_name": "Artist",
        "album_artist_mbid": None,
        "album_title": "Album",
        "year": None,
        "file_path": file_path,
        "source_path": None,
        "file_size_bytes": 1,
        "file_mtime": 0.0,
        "duration_seconds": None,
        "file_format": "flac",
        "bit_rate": None,
        "sample_rate": None,
        "bit_depth": None,
        "source": "scan",
        "confidence": 1.0,
        "is_compilation": 0,
        "tagged_at": None,
    }


async def _seed_album(db: LibraryDB, rg_mbid: str, track_count: int = 2) -> None:
    for i in range(1, track_count + 1):
        await db.upsert_library_file(
            _file_row(rg_mbid, file_path=f"/lib/{rg_mbid}/{i}.flac", track_number=i)
        )


@pytest.mark.asyncio
async def test_get_library_files_for_album_is_case_insensitive(db: LibraryDB):
    """Mixed-case lookup must match the lower-cased stored row."""
    await _seed_album(db, "b1392450-e666-3926-a536-22c65f834433")

    rows = await db.get_library_files_for_album("B1392450-E666-3926-A536-22C65F834433")
    assert len(rows) == 2
    assert {r["track_number"] for r in rows} == {1, 2}


@pytest.mark.asyncio
async def test_has_album_files_and_get_library_files_for_album_agree(db: LibraryDB):
    """The two check sites must not diverge - both case-insensitive or neither."""
    await _seed_album(db, "rg-mixed-case-0001")

    upper = "RG-MIXED-CASE-0001"
    assert await db.has_album_files(upper)
    assert len(await db.get_library_files_for_album(upper)) > 0


@pytest.mark.asyncio
async def test_soft_delete_album_files_is_case_insensitive(db: LibraryDB):
    """soft_delete_album_files must hit the same rows a mixed-case caller passes."""
    await _seed_album(db, "rg-delete-0001")

    deleted_paths = await db.soft_delete_album_files("RG-DELETE-0001")
    assert len(deleted_paths) == 2
    # the rows are now soft-deleted, so a fresh lookup returns nothing
    assert await db.get_library_files_for_album("rg-delete-0001") == []


@pytest.mark.asyncio
async def test_set_album_artist_is_case_insensitive(db: LibraryDB):
    """set_album_artist must stamp rows addressed by a mixed-case MBID."""
    await _seed_album(db, "rg-artist-0001")

    updated = await db.set_album_artist(
        "RG-ARTIST-0001", "artist-mbid-0001", "New Artist"
    )
    assert updated == 2
    rows = await db.get_library_files_for_album("rg-artist-0001")
    assert all(r["album_artist_mbid"] == "artist-mbid-0001" for r in rows)
    assert all(r["album_artist_name"] == "New Artist" for r in rows)

"""Ghost album cleanup - stale library_albums rows with no active files.

library_albums gains rows when downloads are queued (upsert_album) but isn't cleaned
if the download fails or files are removed without remove_album. These ghost rows show
as in-library but have no files. Fixes: get_all_album_mbids only returns file-backed
MBIDs; remove_album succeeds even with no active files, clearing the stale row.
"""

import threading
from pathlib import Path

import pytest

from infrastructure.persistence.library_db import LibraryDB
from services.library_service import LibraryService


@pytest.fixture
def db(tmp_path: Path) -> LibraryDB:
    return LibraryDB(db_path=tmp_path / "test.db", write_lock=threading.Lock())


def _file_row(rg_mbid: str, *, file_path: str, track_number: int = 1) -> dict:
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
        "album_artist_mbid": "artist-1",
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


async def _seed_file(db: LibraryDB, rg_mbid: str, track_number: int = 1) -> None:
    await db.upsert_library_file(
        _file_row(rg_mbid, file_path=f"/lib/{rg_mbid}/{track_number}.flac", track_number=track_number)
    )


@pytest.mark.asyncio
async def test_get_all_album_mbids_excludes_ghost(db: LibraryDB):
    await db.upsert_album({"mbid": "rg-ghost", "title": "Ghost", "artist_mbid": "art-1"})
    await _seed_file(db, "rg-real")
    await db.upsert_album({"mbid": "rg-real", "title": "Real", "artist_mbid": "art-1"})

    mbids = await db.get_all_album_mbids()
    assert "rg-real" in mbids
    assert "rg-ghost" not in mbids


@pytest.mark.asyncio
async def test_get_all_album_mbids_excludes_soft_deleted(db: LibraryDB):
    await _seed_file(db, "rg-doomed")
    await db.upsert_album({"mbid": "rg-doomed", "title": "Doomed", "artist_mbid": "art-1"})
    assert "rg-doomed" in await db.get_all_album_mbids()

    await db.soft_delete_album_files("rg-doomed")
    assert "rg-doomed" not in await db.get_all_album_mbids()


def _build_service(db: LibraryDB) -> LibraryService:
    from unittest.mock import AsyncMock, MagicMock

    library_repo = MagicMock()
    library_repo.is_configured = MagicMock(return_value=True)
    library_repo.get_library_mbids = AsyncMock(return_value=set())
    library_repo.get_requested_mbids = AsyncMock(return_value=set())

    cache = MagicMock()
    cache.delete = AsyncMock()
    cache.clear_prefix = AsyncMock()

    disk_cache = MagicMock()
    disk_cache.delete_album = AsyncMock()
    disk_cache.delete_artist = AsyncMock()

    cover_repo = MagicMock()
    cover_repo.delete_covers_for_album = AsyncMock()
    cover_repo.delete_covers_for_artist = AsyncMock()

    prefs = MagicMock()
    prefs.get_advanced_settings = MagicMock()

    return LibraryService(
        library_repo=library_repo,
        library_db=db,
        memory_cache=cache,
        disk_cache=disk_cache,
        cover_repo=cover_repo,
        preferences_service=prefs,
    )


@pytest.mark.asyncio
async def test_remove_album_succeeds_for_ghost(db: LibraryDB):
    await db.upsert_album({
        "mbid": "rg-ghost",
        "title": "Ghost Album",
        "artist_mbid": "art-1",
        "artist_name": "Ghost Artist",
    })
    service = _build_service(db)

    result = await service.remove_album("rg-ghost")
    assert result.success is True
    assert await db.get_album_by_mbid("rg-ghost") is None


@pytest.mark.asyncio
async def test_remove_album_cleans_materialised_row_for_real_album(db: LibraryDB):
    await _seed_file(db, "rg-real", track_number=1)
    await _seed_file(db, "rg-real", track_number=2)
    await db.upsert_album({
        "mbid": "rg-real",
        "title": "Real Album",
        "artist_mbid": "art-1",
        "artist_name": "Real Artist",
    })
    service = _build_service(db)

    result = await service.remove_album("rg-real", delete_files=False)
    assert result.success is True
    assert await db.get_album_by_mbid("rg-real") is None
    assert await db.get_library_files_for_album("rg-real") == []

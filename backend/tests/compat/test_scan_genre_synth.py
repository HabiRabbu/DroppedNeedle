"""T0.6 - scan-time genre/channels persistence + MBID-less artist synthesis."""

import sqlite3
import threading
from pathlib import Path

import pytest

from infrastructure.persistence.library_db import LibraryDB
from models.audio import AudioInfo, AudioTag
from services.native.library_manager import LibraryManager, _synth_artist_mbid

pytestmark = pytest.mark.asyncio

_RG = "b1392450-e666-3926-a536-22c65f834433"


@pytest.fixture
def manager(tmp_path: Path) -> LibraryManager:
    db = LibraryDB(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    return LibraryManager(db)


def _tag(**overrides) -> AudioTag:
    base = dict(
        title="Airbag", artist="Radiohead", album="OK Computer",
        track_number=1, album_artist="Radiohead", disc_number=1, year=1997,
        genre="Alternative Rock",
    )
    base.update(overrides)
    return AudioTag(**base)


def _info(**overrides) -> AudioInfo:
    base = dict(
        duration_seconds=234.5, bitrate=900, sample_rate=44100, channels=2,
        file_format="flac", file_size_bytes=1234, bit_depth=16,
    )
    base.update(overrides)
    return AudioInfo(**base)


def _artist_row(db: LibraryDB, mbid_lower: str):
    conn = sqlite3.connect(db.db_path)
    try:
        conn.row_factory = sqlite3.Row
        return conn.execute(
            "SELECT * FROM library_artists WHERE mbid_lower = ?", (mbid_lower,)
        ).fetchone()
    finally:
        conn.close()


def _artist_count(db: LibraryDB) -> int:
    conn = sqlite3.connect(db.db_path)
    try:
        return conn.execute("SELECT COUNT(*) FROM library_artists").fetchone()[0]
    finally:
        conn.close()


async def test_scan_persists_genre_and_channels(manager):
    file_id = await manager.upsert_file(
        Path("/music/airbag.flac"), _tag(), _info(channels=2),
        release_group_mbid=_RG, recording_mbid="rec-1", file_mtime=1.0,
    )
    row = await manager._db.get_library_file_by_id(file_id)
    assert row["genre"] == "Alternative Rock"
    assert row["channels"] == 2


async def test_mbid_less_artist_is_synthesised_into_file_and_artists(manager):
    # tag has NO musicbrainz_artist_id / album_artist_id
    file_id = await manager.upsert_file(
        Path("/music/airbag.flac"), _tag(), _info(),
        release_group_mbid=_RG, recording_mbid="rec-1", file_mtime=1.0,
    )
    row = await manager._db.get_library_file_by_id(file_id)
    expected = _synth_artist_mbid("Radiohead")
    assert row["artist_mbid"] == expected
    assert row["album_artist_mbid"] == expected
    # a matching library_artists row was created
    artist = _artist_row(manager._db, expected)
    assert artist is not None
    assert artist["name"] == "Radiohead"
    assert artist["raw_json"] == "{}"


async def test_real_mbid_is_preserved(manager):
    real = "a74b1b7f-71a5-4011-9441-d0b5e4122711"
    file_id = await manager.upsert_file(
        Path("/music/airbag.flac"),
        _tag(musicbrainz_artist_id=real, musicbrainz_album_artist_id=real),
        _info(), release_group_mbid=_RG, recording_mbid="rec-1", file_mtime=1.0,
    )
    row = await manager._db.get_library_file_by_id(file_id)
    assert row["artist_mbid"] == real
    assert row["album_artist_mbid"] == real


async def test_rescan_is_idempotent(manager):
    for _ in range(2):
        await manager.upsert_file(
            Path("/music/airbag.flac"), _tag(), _info(),
            release_group_mbid=_RG, recording_mbid="rec-1", file_mtime=1.0,
        )
    # one file, one synthesised artist row (Radiohead == its own album artist)
    assert _artist_count(manager._db) == 1
    artist = _artist_row(manager._db, _synth_artist_mbid("Radiohead"))
    assert artist["album_count"] == 0  # not clobbered/duplicated


async def test_empty_artist_falls_back_to_unknown_bucket(manager):
    file_id = await manager.upsert_file(
        Path("/music/untagged.flac"),
        _tag(artist="", album_artist=None, genre=None),
        _info(channels=1), release_group_mbid=_RG, recording_mbid="rec-2",
        file_mtime=1.0,
    )
    row = await manager._db.get_library_file_by_id(file_id)
    assert row["artist_mbid"] == _synth_artist_mbid("Unknown Artist")
    assert row["genre"] is None
    assert row["channels"] == 1

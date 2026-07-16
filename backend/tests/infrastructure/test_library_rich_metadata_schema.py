import threading
from pathlib import Path

import pytest

from infrastructure.persistence.library_db import LibraryDB
from models.audio import AudioInfo, AudioTag
from services.native.library_manager import LibraryManager


@pytest.mark.asyncio
async def test_rich_metadata_schema_is_idempotent_and_round_trips(tmp_path):
    db_path = tmp_path / "library.db"
    lock = threading.Lock()
    first = LibraryDB(db_path, lock)
    second = LibraryDB(db_path, lock)
    manager = LibraryManager(first)
    file_id = await manager.upsert_file(
        Path("/music/song.flac"),
        AudioTag(
            title="Song",
            artist="Artist",
            album="Album",
            album_artist="Artist",
            track_number=1,
            title_sort="Song, The",
            disc_subtitle="Bonus",
            original_release_date="1999-02-03",
            replaygain_track_gain=-7.5,
            replaygain_album_gain=-6.0,
            replaygain_track_peak=0.9,
            replaygain_album_peak=0.95,
        ),
        AudioInfo(
            duration_seconds=120,
            bitrate=900,
            sample_rate=44_100,
            channels=2,
            file_format="flac",
            file_size_bytes=100,
            bit_depth=16,
        ),
        release_group_mbid="album-1",
        recording_mbid="recording-1",
    )

    row = await second.get_library_file_by_id(file_id)
    assert row is not None
    assert row["track_sort_name"] == "Song, The"
    assert row["disc_subtitle"] == "Bonus"
    assert row["original_release_date"] == "1999-02-03"
    assert row["replaygain_track_gain"] == -7.5
    assert row["replaygain_album_peak"] == 0.95

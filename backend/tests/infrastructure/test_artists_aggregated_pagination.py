"""get_artists_aggregated: stable pagination and folded-column search upkeep.

Two regressions are guarded here, both on the aggregation-over-library_files path
the /library/artists route actually uses (the legacy get_artists_paginated path is
covered separately in test_library_pagination):

- The artists view froze because the aggregation ORDER BY had no unique tiebreaker:
  distinct artists tying on the sort column could repeat on one page and vanish from
  another, and the duplicate then crashed the keyed list. Paging through every page
  must now yield each group exactly once.
- set_album_artist must keep album_artist_name_folded in sync, so accent-insensitive
  search still finds a release group after its album-artist is reconciled by MBID.
"""

import threading
from pathlib import Path

import pytest

from infrastructure.persistence.library_db import LibraryDB
from models.audio import AudioInfo, AudioTag
from services.native.library_manager import LibraryManager


@pytest.fixture
def manager(tmp_path: Path) -> LibraryManager:
    db = LibraryDB(db_path=tmp_path / "library.db", write_lock=threading.Lock())
    return LibraryManager(db)


def _info() -> AudioInfo:
    return AudioInfo(
        duration_seconds=200.0,
        bitrate=900,
        sample_rate=44100,
        channels=2,
        file_format="flac",
        file_size_bytes=1000,
        bit_depth=16,
    )


async def _add(manager: LibraryManager, path: Path, *, artist: str, artist_mbid: str, rg: str) -> None:
    tag = AudioTag(
        title="t",
        artist=artist,
        album=f"Album {rg}",
        album_artist=artist,
        track_number=1,
        disc_number=1,
        year=2021,
        musicbrainz_release_group_id=rg,
        musicbrainz_album_artist_id=artist_mbid,
    )
    await manager.upsert_file(path, tag, _info(), release_group_mbid=rg, recording_mbid=f"{rg}-r")


@pytest.mark.asyncio
async def test_pagination_no_duplicates_when_artists_tie_on_name(manager, tmp_path):
    # 15 distinct artists (distinct MBID) sharing the SAME name: they tie completely
    # on the name sort, so only the group-key tiebreaker keeps LIMIT/OFFSET stable.
    n = 15
    for i in range(n):
        await _add(
            manager, tmp_path / f"f{i}.flac",
            artist="Various", artist_mbid=f"art-{i:04d}", rg=f"rg-{i:04d}",
        )

    seen: list[str | None] = []
    offset = 0
    page_size = 4  # deliberately does not divide 15 evenly
    while True:
        items, total = await manager.get_artists(
            limit=page_size, offset=offset, sort_by="name", sort_order="asc"
        )
        if not items:
            break
        seen.extend(a.artist_mbid for a in items)
        offset += page_size

    assert total == n
    assert len(seen) == n  # nothing skipped
    assert len(set(seen)) == n  # nothing duplicated across pages


@pytest.mark.asyncio
async def test_set_album_artist_keeps_folded_search_in_sync(manager, tmp_path):
    # a file imported without an album-artist MBID, later reconciled to an accented
    # name, must stay findable by the unaccented spelling (folded column updated).
    await _add(manager, tmp_path / "x.flac", artist="Unknown", artist_mbid="", rg="rg-x")
    await manager._db.set_album_artist("rg-x", "art-bey", "Beyoncé")

    items, total = await manager.get_artists(q="beyonce")

    assert total == 1
    assert items[0].artist_name == "Beyoncé"

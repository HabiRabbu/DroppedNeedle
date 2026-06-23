"""Library search is accent- and case-insensitive (fold() in LibraryDB).

A keyboard that can't type the accent in 'The Marías' must still surface the
band when the user types 'marias'. Covers all three search paths the library
search box fans out to (albums / artists / tracks) plus search_tracks, and
guards that folding does not break LIKE-escaping or turn into a match-everything.
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


async def _add(manager: LibraryManager, path: Path, *, title: str, artist: str,
               album: str, rg: str, rec: str) -> None:
    tag = AudioTag(
        title=title,
        artist=artist,
        album=album,
        album_artist=artist,
        track_number=1,
        disc_number=1,
        year=2021,
        musicbrainz_release_group_id=rg,
        musicbrainz_artist_id=f"art-{rg}",
    )
    await manager.upsert_file(
        path, tag, _info(), release_group_mbid=rg, recording_mbid=rec
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("query", ["marias", "Marías", "MARIAS", "marías"])
async def test_album_search_ignores_accent_and_case(manager, tmp_path, query):
    await _add(
        manager, tmp_path / "a.flac",
        title="Hush", artist="The Marías", album="Submarine",
        rg="rg-marias", rec="rec-1",
    )
    items, total = await manager.get_albums_page(q=query)
    assert total == 1, f"query {query!r} should match 'The Marías'"
    assert items[0].album_artist_name == "The Marías"


@pytest.mark.asyncio
async def test_reported_query_the_marias_finds_band(manager, tmp_path):
    # the exact reported scenario: typing "The Marias" (no accent, multi-word,
    # leading "The") must surface "The Marías" in both album and artist results
    await _add(
        manager, tmp_path / "a.flac",
        title="Hush", artist="The Marías", album="Submarine",
        rg="rg-marias", rec="rec-1",
    )
    albums, album_total = await manager.get_albums_page(q="The Marias")
    assert album_total == 1
    assert albums[0].album_artist_name == "The Marías"
    artists, artist_total = await manager.get_artists(q="The Marias")
    assert artist_total == 1
    assert artists[0].artist_name == "The Marías"


@pytest.mark.asyncio
async def test_artist_search_ignores_accent(manager, tmp_path):
    await _add(
        manager, tmp_path / "a.flac",
        title="Hush", artist="The Marías", album="Submarine",
        rg="rg-marias", rec="rec-1",
    )
    items, total = await manager.get_artists(q="marias")
    assert total == 1
    assert items[0].artist_name == "The Marías"


@pytest.mark.asyncio
async def test_track_title_search_ignores_accent(manager, tmp_path):
    await _add(
        manager, tmp_path / "b.flac",
        title="Naïve", artist="The Kooks", album="Inside In",
        rg="rg-kooks", rec="rec-2",
    )
    items, total = await manager.get_tracks_page(q="naive")
    assert total == 1
    assert items[0].title == "Naïve"


@pytest.mark.asyncio
async def test_search_tracks_ignores_accent(manager, tmp_path):
    await _add(
        manager, tmp_path / "c.flac",
        title="Halo", artist="Beyoncé", album="I Am",
        rg="rg-bey", rec="rec-3",
    )
    rows = await manager.search_tracks("beyonce")
    assert [r["track_title"] for r in rows] == ["Halo"]


@pytest.mark.asyncio
async def test_search_still_excludes_non_matches(manager, tmp_path):
    # folding must not collapse distinct strings into a match-everything filter
    await _add(
        manager, tmp_path / "a.flac",
        title="Hush", artist="The Marías", album="Submarine",
        rg="rg-marias", rec="rec-1",
    )
    items, total = await manager.get_albums_page(q="radiohead")
    assert total == 0
    assert items == []


@pytest.mark.asyncio
async def test_like_metacharacters_stay_literal_through_fold(manager, tmp_path):
    # ESCAPE '\' survives folding: '%' must match literally, not as a wildcard
    await _add(
        manager, tmp_path / "pct.flac",
        title="Cent", artist="50%", album="Discount",
        rg="rg-pct", rec="rec-pct",
    )
    await _add(
        manager, tmp_path / "plain.flac",
        title="Plain", artist="5000 Ways", album="Other",
        rg="rg-plain", rec="rec-plain",
    )
    items, total = await manager.get_artists(q="50%")
    assert total == 1
    assert items[0].artist_name == "50%"

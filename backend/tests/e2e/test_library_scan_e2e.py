"""End-to-end library scan: walk a fixture directory of real audio files, identify
them, and assert the resulting ``library_files`` + manual-review rows.

Network-free: the fixtures used here carry full MBIDs (Tier 1), so MusicBrainz and
AcoustID are never consulted - both boundaries are mocked to a no-match verdict to
prove they are not needed. A no-tags file falls through to Tier 4 (manual review).
"""

import shutil
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from infrastructure.audio.tagger import AudioTagger
from infrastructure.persistence.library_db import LibraryDB
from infrastructure.persistence.scan_state_store import ScanStateStore
from infrastructure.sse_publisher import SSEPublisher
from models.audio import FingerprintResult
from models.download import TargetAlbum  # noqa: F401 - ensures models import cleanly
from services.native.library_manager import LibraryManager
from services.native.library_scanner import LibraryScanner
from services.native.musicbrainz_matcher import MatchResult

FIXTURES = Path(__file__).resolve().parent.parent / "fixtures" / "library"
_RG_OK_COMPUTER = "b1392450-e666-3926-a536-22c65f834433"  # flac_full_01/02


@pytest.fixture(autouse=True)
def _fast_artist_backoff(monkeypatch):
    monkeypatch.setattr("services.native.library_scanner._ARTIST_BREAKER_WAIT_S", 0.0)


def _build_scanner(tmp_path: Path):
    lock = threading.Lock()
    db_path = tmp_path / "library.db"
    db = LibraryDB(db_path=db_path, write_lock=lock)
    manager = LibraryManager(db)
    state = ScanStateStore(db_path=db_path, write_lock=lock)
    # Both network boundaries return "no match" - Tier 1 must carry the scan.
    mb = AsyncMock()
    mb.text_match = AsyncMock(return_value=MatchResult(confidence=0.0))
    mb.resolve_recording_to_release_group = AsyncMock(return_value=None)
    fp = AsyncMock()
    fp.fingerprint = AsyncMock(return_value=FingerprintResult(status="disabled"))
    album = AsyncMock()
    album.identify = AsyncMock(return_value=None)
    album.resolve_release_group_artist = AsyncMock(return_value=(None, None))
    scanner = LibraryScanner(AudioTagger(), fp, mb, album, manager, state, SSEPublisher())
    return scanner, manager, state, mb


def _seed_library(tmp_path: Path) -> Path:
    """Lay out 5 files across 4 album folders (4 Tier-1 matches, 1 unmatched)."""
    library = tmp_path / "library"
    layout = {
        "OK Computer": ["flac_full_01.flac", "flac_full_02.flac"],
        "Achtung Baby": ["mp3_full_01.mp3"],
        "Mezzanine": ["m4a_full_01.m4a"],
        "Unknown": ["flac_no_tags.flac"],
    }
    for folder, names in layout.items():
        dest_dir = library / folder
        dest_dir.mkdir(parents=True, exist_ok=True)
        for name in names:
            shutil.copy(FIXTURES / name, dest_dir / name)
    return library


@pytest.mark.asyncio
async def test_scan_populates_library_files(tmp_path: Path):
    scanner, manager, state, mb = _build_scanner(tmp_path)
    library = _seed_library(tmp_path)

    await scanner.scan([library])

    # Four MBID-tagged files identified at Tier 1, written to library_files.
    file_index = await manager.get_file_index()
    assert len(file_index) == 4

    final_state = await state.get_state()
    assert final_state["status"] == "idle"  # returns to idle once a scan completes
    assert final_state["matched_files"] == 4

    # The two OK Computer tracks group under one album at confidence 1.0 (Tier 1).
    assert await manager.has_album(_RG_OK_COMPUTER) is True
    rows = await manager.get_file_rows_for_album(_RG_OK_COMPUTER)
    assert len(rows) == 2
    assert all(float(r["confidence"]) == 1.0 for r in rows)
    assert all(r["source"] == "scan" for r in rows)

    # The no-tags file could not be identified -> manual review (Tier 4).
    unmatched = await manager.get_unmatched()
    assert len(unmatched) == 1
    assert "flac_no_tags" in unmatched[0].file_path

    # MusicBrainz returned no match for every file it was consulted on, yet four
    # files still matched - proving they were identified at Tier 1 (MBID-in-tags),
    # with no successful network lookup required.
    mb.resolve_recording_to_release_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_rescan_is_incremental(tmp_path: Path):
    """A second scan with nothing changed re-counts matches without re-importing."""
    scanner, manager, state, _mb = _build_scanner(tmp_path)
    library = _seed_library(tmp_path)

    await scanner.scan([library])
    first = await manager.get_file_index()

    await scanner.scan([library])
    second = await manager.get_file_index()

    assert first.keys() == second.keys()
    final_state = await state.get_state()
    assert final_state["status"] == "idle"  # returns to idle once a scan completes
    assert final_state["matched_files"] == 4

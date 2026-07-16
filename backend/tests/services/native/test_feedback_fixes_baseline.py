"""Phase 0 fixtures that pin the reviewed legacy failures before replacement."""

import asyncio
import threading
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from api.v1.schemas.settings import LibraryScanScheduleSettings
from core import tasks
from infrastructure.observability.library_metrics import LibraryMetrics
from infrastructure.persistence.library_db import LibraryDB
from models.album import Track
from services.native.album_matcher import (
    LocalTrack,
    MBTrack,
    _ReleaseMeta,
    score_release,
)
from services.native.coverage import match_rows_to_tracks


class _LegacySchedulePreferences:
    def __init__(self) -> None:
        self.schedule = LibraryScanScheduleSettings(scan_frequency="5min")

    def get_library_scan_schedule(self) -> LibraryScanScheduleSettings:
        return self.schedule

    def save_library_scan_schedule(
        self, _schedule: LibraryScanScheduleSettings
    ) -> None:
        return None

    def get_typed_library_settings_raw(self) -> SimpleNamespace:
        return SimpleNamespace(library_roots=[SimpleNamespace(path="/music")])


@pytest.mark.asyncio
async def test_baseline_long_scan_restarts_from_started_at(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The second call is the reported bug; Phase 4 changes this expectation to one call."""
    started = datetime(2026, 7, 10, 9, 0).timestamp()
    now = datetime(2026, 7, 13, 9, 0)
    monkeypatch.setattr(tasks, "datetime", SimpleNamespace(now=lambda: now))
    scan_calls = 0

    async def scan(_paths: list) -> None:
        nonlocal scan_calls
        scan_calls += 1
        if scan_calls == 2:
            raise asyncio.CancelledError

    state = SimpleNamespace(
        get_state=AsyncMock(return_value={"status": "idle", "started_at": started})
    )
    scanner = SimpleNamespace(scan=scan)

    await tasks.auto_scan_library_periodically(
        scanner, state, _LegacySchedulePreferences()
    )

    assert scan_calls == 2


def test_baseline_forced_assignment_accepts_zero_supported_titles() -> None:
    """Matching positions/durations force two unrelated titles through the old gate."""
    local = [
        LocalTrack(
            path=f"local-{index}",
            title=title,
            artist="Artist",
            album="Album",
            track_number=index,
            duration_seconds=180,
        )
        for index, title in enumerate(("North", "South"), 1)
    ]
    candidate = [
        MBTrack(
            title=title,
            position=index,
            disc=1,
            absolute_position=index,
            length_ms=180_000,
            recording_mbid=f"recording-{index}",
        )
        for index, title in enumerate(("Orange", "Purple"), 1)
    ]
    match = score_release(
        local,
        candidate,
        _ReleaseMeta(
            release_group_mbid="rg-wrong",
            release_mbid="release-wrong",
            album_title="Album",
            artist="Artist",
            is_various=False,
        ),
    )

    assert match.accepted is True
    assert len(match.assignments) == 2


def test_baseline_album_coverage_refutes_forced_scanner_assignment() -> None:
    rows = [
        {
            "id": f"local-{index}",
            "track_title": title,
            "duration_seconds": 180,
            "disc_number": 1,
            "track_number": 0,
            "recording_mbid": None,
        }
        for index, title in enumerate(("North", "North 2"), 1)
    ]
    expected = [
        Track(position=index, title=title, length=180_000)
        for index, title in enumerate(("Nirth", "Nirth 2"), 1)
    ]

    # The legacy album scorer accepts this fuzzy pair, but coverage requires stronger
    # title support when position metadata is absent.
    local = [
        LocalTrack(
            path=row["id"],
            title=row["track_title"],
            artist="Artist",
            album="Album",
            track_number=0,
            duration_seconds=180,
        )
        for row in rows
    ]
    candidate = [
        MBTrack(
            title=track.title,
            position=track.position,
            disc=1,
            absolute_position=track.position,
            length_ms=track.length,
        )
        for track in expected
    ]
    accepted = score_release(
        local,
        candidate,
        _ReleaseMeta(
            release_group_mbid="rg-wrong",
            release_mbid="release-wrong",
            album_title="Album",
            artist="Artist",
            is_various=False,
        ),
    )

    covered, orphans, matched_ids = match_rows_to_tracks(rows, expected)

    assert accepted.accepted is True
    assert covered == 0
    assert len(orphans) == 2
    assert matched_ids == []


@pytest.mark.asyncio
async def test_baseline_rediscovery_reopens_rejected_review(tmp_path) -> None:
    database = LibraryDB(tmp_path / "library.db", threading.Lock())
    row = {"file_path": "/music/Artist/Album/01.flac", "source": "text_match"}
    await database.add_to_manual_review(row)
    review = (await database.get_unmatched_files())[0]
    assert await database.resolve_manual_review(review["id"], "rejected") is True

    await database.add_to_manual_review(row)

    reopened = await database.get_unmatched_files()
    assert len(reopened) == 1
    assert reopened[0]["resolution"] is None


@pytest.mark.asyncio
async def test_baseline_unresolved_path_is_reprocessed_by_incremental_scans(
    tmp_path,
) -> None:
    database = LibraryDB(tmp_path / "library.db", threading.Lock())
    path = "/music/Unknown/Loose Track.flac"
    await database.add_to_manual_review({"file_path": path, "source": "text_match"})

    # The deployed incremental index only contains identified library_files rows, so the
    # scanner cannot use this review row to recognize unchanged unresolved work.
    assert path not in await database.get_file_index()


def test_baseline_reidentify_feedback_stops_after_fixed_refresh_delays() -> None:
    source = (
        Path(__file__).parents[4]
        / "frontend"
        / "src"
        / "lib"
        / "queries"
        / "library"
        / "LibraryMutations.svelte.ts"
    ).read_text(encoding="utf-8")

    assert "RESCAN_REFRESH_DELAYS_MS = [2500, 6000]" in source
    assert "for (const delay of RESCAN_REFRESH_DELAYS_MS)" in source


def test_phase0_metrics_capture_required_aggregate_shapes() -> None:
    metrics = LibraryMetrics()
    metrics.increment("walks")
    metrics.increment("stats", 3)
    metrics.observe("write_lock_wait_seconds", 0.01)
    metrics.observe("write_lock_wait_seconds", 0.02)
    metrics.set_peak("wal_bytes", 4096)
    metrics.sample_rss()

    snapshot = metrics.snapshot()

    assert snapshot.counters == {"walks": 1, "stats": 3}
    assert snapshot.distributions["write_lock_wait_seconds"].p95 == 0.02
    assert snapshot.peaks["wal_bytes"] == 4096

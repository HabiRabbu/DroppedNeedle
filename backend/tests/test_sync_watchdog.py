"""Tests for the adaptive watchdog timeout in the orchestrator."""

import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.precache.orchestrator import LibraryPrecacheService
from services.cache_status_service import CacheStatusService
from core.exceptions import ExternalServiceError


@pytest.fixture(autouse=True)
def _reset_singleton():
    """Reset CacheStatusService singleton between tests."""
    CacheStatusService._instance = None
    yield
    CacheStatusService._instance = None


def _make_settings():
    s = MagicMock()
    s.sync_stall_timeout_minutes = 0.05  # 3 seconds for test speed
    s.sync_max_timeout_hours = 0.01  # 36 seconds
    s.audiodb_enabled = False
    s.audiodb_prewarm_concurrency = 4
    s.audiodb_prewarm_delay = 0.0
    s.batch_artist_images = 10
    s.batch_albums = 8
    s.delay_albums = 0.0
    s.delay_artists = 0.0
    s.artist_discovery_precache_delay = 0.0
    return s


def _make_prefs(settings=None):
    if settings is None:
        settings = _make_settings()
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = settings
    return prefs


def _make_service(prefs=None):
    if prefs is None:
        prefs = _make_prefs()
    return LibraryPrecacheService(
        library_repo=AsyncMock(),
        cover_repo=AsyncMock(),
        preferences_service=prefs,
        sync_state_store=AsyncMock(),
        genre_index=AsyncMock(),
        library_db=AsyncMock(),
    )


class TestAdaptiveWatchdog:
    @pytest.mark.asyncio
    async def test_stall_detection_cancels_sync(self):
        """Sync that stops making progress should be cancelled by the watchdog."""
        settings = _make_settings()
        settings.sync_stall_timeout_minutes = 0.02  # 1.2 seconds
        svc = _make_service(_make_prefs(settings))

        async def stalling_precache(artists, albums, status_service, resume=False):
            await status_service.start_sync('artists', 1)
            await asyncio.sleep(30)  # Stall forever

        with patch.object(svc, '_do_precache', side_effect=stalling_precache):
            with pytest.raises(ExternalServiceError, match="stalled"):
                await svc.precache_library_resources([], [])

        assert True

    @pytest.mark.asyncio
    async def test_progressing_sync_completes(self):
        """A sync that makes steady progress should complete without watchdog interference."""
        settings = _make_settings()
        settings.sync_stall_timeout_minutes = 0.1  # 6 seconds
        svc = _make_service(_make_prefs(settings))

        async def fast_precache(artists, albums, status_service, resume=False):
            await status_service.start_sync('artists', 2)
            await status_service.update_progress(1, "artist1")
            await asyncio.sleep(0.1)
            await status_service.update_progress(2, "artist2")

        with patch.object(svc, '_do_precache', side_effect=fast_precache):
            await svc.precache_library_resources([], [])

        assert True

    @pytest.mark.asyncio
    async def test_max_timeout_cancels_even_with_progress(self):
        """Max timeout should cancel even if progress is being made."""
        settings = _make_settings()
        settings.sync_stall_timeout_minutes = 10  # Very generous stall timeout
        settings.sync_max_timeout_hours = 0.0003  # ~1 second
        svc = _make_service(_make_prefs(settings))

        async def slow_but_progressing(artists, albums, status_service, resume=False):
            await status_service.start_sync('artists', 100)
            for i in range(100):
                await status_service.update_progress(i + 1, f"artist{i}")
                await asyncio.sleep(0.5)

        with patch.object(svc, '_do_precache', side_effect=slow_but_progressing):
            with pytest.raises(ExternalServiceError, match="maximum timeout"):
                await svc.precache_library_resources([], [])

        assert True

    @pytest.mark.asyncio
    async def test_error_in_precache_propagates(self):
        """Errors in the precache task should propagate through the watchdog."""
        svc = _make_service()

        async def failing_precache(artists, albums, status_service, resume=False):
            raise ValueError("something broke")

        with patch.object(svc, '_do_precache', side_effect=failing_precache):
            with pytest.raises(ValueError, match="something broke"):
                await svc.precache_library_resources([], [])

        assert True

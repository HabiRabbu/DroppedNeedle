"""Tests for sync coordinator: cooldown on success only, future dedup, race safety."""
import asyncio
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


def _make_library_service(**overrides):
    """Build a minimal LibraryService with mocked deps."""
    from services.library_service import LibraryService

    library_repo = overrides.get("library_repo", AsyncMock())
    library_repo.is_configured = MagicMock(return_value=True)
    library_repo.get_library = overrides.get("get_library", AsyncMock(return_value=[]))
    library_repo.get_artists_from_library = overrides.get(
        "get_artists_from_library", AsyncMock(return_value=[])
    )

    library_db = overrides.get("library_db", AsyncMock())
    library_db.save_library = AsyncMock()

    prefs = overrides.get("prefs", MagicMock())
    prefs.get_advanced_settings.return_value = MagicMock(
        cache_ttl_library_sync=30,
    )

    svc = LibraryService(
        library_repo=library_repo,
        library_db=library_db,
        cover_repo=MagicMock(),
        preferences_service=prefs,
    )
    return svc


class TestCooldownOnlyOnSuccess:
    @pytest.mark.asyncio
    async def test_failed_sync_does_not_set_cooldown(self):
        svc = _make_library_service()
        svc._library_repo.get_library = AsyncMock(side_effect=RuntimeError("DNS fail"))

        with patch("services.library_service.CacheStatusService") as mock_css:
            mock_css.return_value.is_syncing.return_value = False

            with pytest.raises(Exception, match="DNS fail"):
                await svc.sync_library()

        assert svc._last_sync_time == 0.0, "cooldown must NOT activate on failure"

    @pytest.mark.asyncio
    async def test_successful_sync_sets_cooldown(self):
        svc = _make_library_service()

        with patch("services.library_service.CacheStatusService") as mock_css:
            mock_css.return_value.is_syncing.return_value = False

            before = time.time()
            result = await svc.sync_library()
            after = time.time()

        assert result.status == "success"
        assert before <= svc._last_sync_time <= after

    @pytest.mark.asyncio
    async def test_retry_after_failed_sync_is_not_cooldown_blocked(self):
        call_count = 0

        async def fail_then_succeed(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise RuntimeError("temporary failure")
            return []

        svc = _make_library_service()
        svc._library_repo.get_library = fail_then_succeed

        with patch("services.library_service.CacheStatusService") as mock_css:
            mock_css.return_value.is_syncing.return_value = False

            with pytest.raises(Exception, match="temporary failure"):
                await svc.sync_library()

            result = await svc.sync_library()

        assert result.status == "success"


class TestSyncFutureDedup:
    @pytest.mark.asyncio
    async def test_concurrent_syncs_deduplicated(self):
        """Two concurrent sync calls should result in exactly one library call."""
        call_count = 0
        sync_event = asyncio.Event()

        async def slow_get_library(**kwargs):
            nonlocal call_count
            call_count += 1
            sync_event.set()
            await asyncio.sleep(0.05)
            return []

        svc = _make_library_service()
        svc._library_repo.get_library = slow_get_library

        with patch("services.library_service.CacheStatusService") as mock_css:
            mock_css.return_value.is_syncing.return_value = False

            results = await asyncio.gather(
                svc.sync_library(),
                svc.sync_library(),
            )

        assert all(r.status == "success" for r in results)
        assert call_count == 1, f"Expected 1 library call, got {call_count}"

    @pytest.mark.asyncio
    async def test_concurrent_sync_failure_propagates_to_waiter(self):
        """When the producer fails, deduped waiters get the real exception."""
        async def failing_get_library(**kwargs):
            await asyncio.sleep(0.05)
            raise RuntimeError("library DNS failure")

        svc = _make_library_service()
        svc._library_repo.get_library = failing_get_library

        with patch("services.library_service.CacheStatusService") as mock_css:
            mock_css.return_value.is_syncing.return_value = False

            results = await asyncio.gather(
                svc.sync_library(),
                svc.sync_library(),
                return_exceptions=True,
            )

        # Both should get an error, not hang or get CancelledError
        for r in results:
            assert isinstance(r, Exception)
            assert not isinstance(r, asyncio.CancelledError), \
                "Waiter got CancelledError instead of the real exception"

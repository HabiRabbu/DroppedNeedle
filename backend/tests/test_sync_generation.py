"""Tests for MUS-19: sync generation counter, false-failed status, cancel, progress clamp."""

import asyncio
import os

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.cache_status_service import CacheStatusService, CacheSyncProgress


def _make_status_service() -> CacheStatusService:
    store = AsyncMock()
    store.save_sync_state = AsyncMock()
    svc = CacheStatusService(store)
    svc._sse_subscribers = []
    return svc


class TestGenerationCounter:
    """Generation counter rejects stale writes from old syncs."""

    @pytest.mark.asyncio
    async def test_start_sync_returns_generation(self):
        svc = _make_status_service()
        gen1 = await svc.start_sync('artists', 10)
        assert gen1 >= 1
        gen2 = await svc.start_sync('artists', 5)
        assert gen2 == gen1 + 1

    @pytest.mark.asyncio
    async def test_stale_update_progress_rejected(self):
        svc = _make_status_service()
        gen1 = await svc.start_sync('artists', 10)
        gen2 = await svc.start_sync('artists', 5)

        await svc.update_progress(3, 'old item', generation=gen1)
        progress = svc.get_progress()
        assert progress.processed_items == 0, "Stale generation write should be rejected"

        await svc.update_progress(2, 'new item', generation=gen2)
        progress = svc.get_progress()
        assert progress.processed_items == 2

    @pytest.mark.asyncio
    async def test_stale_update_phase_rejected(self):
        svc = _make_status_service()
        gen1 = await svc.start_sync('artists', 10)
        gen2 = await svc.start_sync('albums', 5)

        await svc.update_phase('audiodb_prewarm', 100, generation=gen1)
        progress = svc.get_progress()
        assert progress.phase == 'albums', "Stale generation should not change phase"

    @pytest.mark.asyncio
    async def test_stale_complete_sync_rejected(self):
        svc = _make_status_service()
        gen1 = await svc.start_sync('artists', 10)
        _gen2 = await svc.start_sync('artists', 5)

        await svc.complete_sync(generation=gen1)
        progress = svc.get_progress()
        assert progress.is_syncing is True, "Stale complete_sync should not stop current sync"

    @pytest.mark.asyncio
    async def test_stale_skip_phase_rejected(self):
        svc = _make_status_service()
        gen1 = await svc.start_sync('artists', 10)
        gen2 = await svc.start_sync('albums', 5)

        await svc.skip_phase('albums', generation=gen1)
        progress = svc.get_progress()
        assert progress.phase == 'albums', "Stale skip_phase should be rejected"

    @pytest.mark.asyncio
    async def test_stale_persist_progress_rejected(self):
        svc = _make_status_service()
        gen1 = await svc.start_sync('artists', 10)
        _gen2 = await svc.start_sync('artists', 5)

        svc._sync_state_store.save_sync_state.reset_mock()
        await svc.persist_progress(generation=gen1)
        svc._sync_state_store.save_sync_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_generation_zero_bypasses_guard(self):
        """generation=0 (default) always passes through, for backward compatibility."""
        svc = _make_status_service()
        _gen = await svc.start_sync('artists', 10)

        await svc.update_progress(5, 'item', generation=0)
        progress = svc.get_progress()
        assert progress.processed_items == 5


class TestProgressClamp:
    """progress_percent is clamped to 100."""

    @pytest.mark.asyncio
    async def test_percent_clamped_to_100(self):
        svc = _make_status_service()
        await svc.start_sync('artists', 5)
        await svc.update_progress(20, 'overflow')
        progress = svc.get_progress()
        assert progress.progress_percent <= 100


class TestCancelSync:
    """Cancel endpoint and cancellation behavior."""

    @pytest.mark.asyncio
    async def test_cancel_always_sets_event(self):
        svc = _make_status_service()
        assert not svc.is_cancelled()
        await svc.cancel_current_sync()
        assert svc.is_cancelled()

    @pytest.mark.asyncio
    async def test_cancel_works_when_not_syncing(self):
        """Cancel should work even when is_syncing is False (post-completion AudioDB)."""
        svc = _make_status_service()
        await svc.cancel_current_sync()
        assert svc.is_cancelled()


class TestCancelRoute:
    """Cancel sync API endpoint."""

    @pytest.mark.skipif(
        not os.access('/app', os.W_OK),
        reason="Route tests require /app to be writable (Docker environment)",
    )
    def test_cancel_endpoint_calls_service_and_registry(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from api.v1.routes.cache_status import router
        from core.dependencies import get_cache_status_service

        mock_svc = MagicMock()
        mock_svc.cancel_current_sync = AsyncMock()
        mock_svc.wait_for_completion = AsyncMock()

        app = FastAPI()
        app.include_router(router)
        app.dependency_overrides[get_cache_status_service] = lambda: mock_svc

        with patch("core.task_registry.TaskRegistry") as MockRegistry:
            mock_registry_instance = MagicMock()
            MockRegistry.get_instance.return_value = mock_registry_instance

            client = TestClient(app)
            resp = client.post("/cache/sync/cancel")

        assert resp.status_code == 200
        assert resp.json() == {"status": "cancelled"}
        mock_svc.cancel_current_sync.assert_awaited_once()
        mock_registry_instance.cancel.assert_called_once_with("precache-library")
        mock_svc.wait_for_completion.assert_awaited_once()


class TestRestoreAudioDBPhase:
    """restore_from_persistence handles audiodb_prewarm phase."""

    @pytest.mark.asyncio
    async def test_audiodb_prewarm_phase_restores(self):
        svc = _make_status_service()
        svc._sync_state_store.get_sync_state = AsyncMock(return_value={
            'status': 'running',
            'phase': 'audiodb_prewarm',
            'total_artists': 100,
            'processed_artists': 100,
            'total_albums': 50,
            'processed_albums': 50,
            'started_at': 1000,
        })
        await svc.restore_from_persistence()
        progress = svc.get_progress()
        assert progress.is_syncing is True
        assert progress.phase == 'audiodb_prewarm'
        assert progress.total_items == 0

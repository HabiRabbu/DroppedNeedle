"""Tests for artist discovery precache progress reporting and error handling."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from services.artist_discovery_service import ArtistDiscoveryService


def _make_service(*, lb_configured: bool = True, lastfm_enabled: bool = False):
    lb_repo = MagicMock()
    lb_repo.is_configured.return_value = lb_configured

    lastfm_repo = MagicMock() if lastfm_enabled else None
    prefs = MagicMock()
    prefs.is_lastfm_enabled.return_value = lastfm_enabled
    advanced = MagicMock()
    advanced.artist_discovery_precache_concurrency = 3
    prefs.get_advanced_settings.return_value = advanced

    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()

    library_db = AsyncMock()
    library_db.get_all_artist_mbids = AsyncMock(return_value=set())

    svc = ArtistDiscoveryService(
        listenbrainz_repo=lb_repo,
        musicbrainz_repo=MagicMock(),
        library_db=library_db,
        library_repo=MagicMock(),
        memory_cache=cache,
        lastfm_repo=lastfm_repo,
        preferences_service=prefs,
    )
    return svc


@pytest.mark.asyncio
async def test_progress_updates_on_success():
    svc = _make_service()
    status = MagicMock()
    status.update_progress = AsyncMock()
    status.is_cancelled = MagicMock(return_value=False)

    with (
        patch.object(svc, "get_similar_artists", new_callable=AsyncMock, return_value=MagicMock()),
        patch.object(svc, "get_top_songs", new_callable=AsyncMock, return_value=MagicMock()),
        patch.object(svc, "get_top_albums", new_callable=AsyncMock, return_value=MagicMock()),
    ):
        await svc.precache_artist_discovery(
            ["mbid-a", "mbid-b"],
            delay=0,
            status_service=status,
            mbid_to_name={"mbid-a": "Artist A", "mbid-b": "Artist B"},
        )

    assert status.update_progress.call_count == 2
    status.update_progress.assert_any_call(1, current_item="Artist A", generation=0)
    status.update_progress.assert_any_call(2, current_item="Artist B", generation=0)


@pytest.mark.asyncio
async def test_progress_updates_even_on_failure():
    svc = _make_service()
    status = MagicMock()
    status.update_progress = AsyncMock()
    status.is_cancelled = MagicMock(return_value=False)

    with (
        patch.object(svc, "get_similar_artists", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        patch.object(svc, "get_top_songs", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
        patch.object(svc, "get_top_albums", new_callable=AsyncMock, side_effect=RuntimeError("boom")),
    ):
        await svc.precache_artist_discovery(
            ["mbid-a", "mbid-b", "mbid-c"],
            delay=0,
            status_service=status,
            mbid_to_name={"mbid-a": "A", "mbid-b": "B", "mbid-c": "C"},
        )

    assert status.update_progress.call_count == 3
    status.update_progress.assert_any_call(1, current_item="A", generation=0)
    status.update_progress.assert_any_call(2, current_item="B", generation=0)
    status.update_progress.assert_any_call(3, current_item="C", generation=0)


@pytest.mark.asyncio
async def test_progress_updates_on_mixed_success_and_failure():
    svc = _make_service()
    status = MagicMock()
    status.update_progress = AsyncMock()
    status.is_cancelled = MagicMock(return_value=False)

    call_count = 0

    async def sometimes_fail(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise RuntimeError("transient")
        return MagicMock()

    with (
        patch.object(svc, "get_similar_artists", new_callable=AsyncMock, side_effect=sometimes_fail),
        patch.object(svc, "get_top_songs", new_callable=AsyncMock, side_effect=sometimes_fail),
        patch.object(svc, "get_top_albums", new_callable=AsyncMock, side_effect=sometimes_fail),
    ):
        await svc.precache_artist_discovery(
            ["mbid-1", "mbid-2"],
            delay=0,
            status_service=status,
        )

    assert status.update_progress.call_count == 2


@pytest.mark.asyncio
async def test_cached_artists_still_update_progress():
    svc = _make_service()
    status = MagicMock()
    status.update_progress = AsyncMock()
    status.is_cancelled = MagicMock(return_value=False)

    svc._cache.get = AsyncMock(return_value="cached-value")

    await svc.precache_artist_discovery(
        ["mbid-a", "mbid-b"],
        delay=0,
        status_service=status,
        mbid_to_name={"mbid-a": "A", "mbid-b": "B"},
    )

    assert status.update_progress.call_count == 2

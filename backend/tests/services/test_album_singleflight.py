import asyncio

import pytest
from unittest.mock import AsyncMock, MagicMock

from api.v1.schemas.album import AlbumInfo
from core.exceptions import ResourceNotFoundError
from services.album_service import AlbumService


MBID = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"


def _fake_album_info() -> AlbumInfo:
    return AlbumInfo(
        title="Test Album",
        artist_name="Test Artist",
        musicbrainz_id=MBID,
        artist_id="artist-" + MBID,
        release_date="2024",
    )


def _make_service() -> AlbumService:
    library_repo = AsyncMock()
    library_repo.is_configured.return_value = False
    mb = AsyncMock()
    lib_cache = AsyncMock()
    mem_cache = AsyncMock()
    mem_cache.get = AsyncMock(return_value=None)
    mem_cache.set = AsyncMock()
    disk_cache = MagicMock()
    disk_cache.get_album = AsyncMock(return_value=None)
    disk_cache.set_album = AsyncMock()
    prefs = MagicMock()
    audiodb_img = MagicMock()
    audiodb_img.fetch_and_cache_album_images = AsyncMock(return_value=None)

    svc = AlbumService(
        library_repo=library_repo,
        mb_repo=mb,
        library_db=lib_cache,
        memory_cache=mem_cache,
        disk_cache=disk_cache,
        preferences_service=prefs,
        audiodb_image_service=audiodb_img,
    )
    return svc


class TestAlbumSingleflight:
    @pytest.mark.asyncio
    async def test_concurrent_calls_fetch_once(self):
        """Multiple concurrent get_album_info calls for the same ID
        should only invoke _do_get_album_info once."""
        svc = _make_service()
        call_count = 0
        fake = _fake_album_info()

        async def counting_fetch(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            await asyncio.sleep(0.05)
            return fake

        svc._do_get_album_info = counting_fetch

        results = await asyncio.gather(
            svc.get_album_info(MBID),
            svc.get_album_info(MBID),
            svc.get_album_info(MBID),
        )

        assert call_count == 1
        assert all(r.title == "Test Album" for r in results)

    @pytest.mark.asyncio
    async def test_singleflight_cleared_after_completion(self):
        """After completion, the in-flight dict should be empty."""
        svc = _make_service()
        fake = _fake_album_info()

        async def quick_fetch(*args, **kwargs):
            return fake

        svc._do_get_album_info = quick_fetch

        await svc.get_album_info(MBID)
        assert MBID not in svc._album_in_flight

    @pytest.mark.asyncio
    async def test_singleflight_propagates_exception(self):
        """If fetch raises, all concurrent callers should get the exception."""
        svc = _make_service()

        async def failing_fetch(*args, **kwargs):
            await asyncio.sleep(0.05)
            raise RuntimeError("upstream timeout")

        svc._do_get_album_info = failing_fetch

        results = await asyncio.gather(
            svc.get_album_info(MBID),
            svc.get_album_info(MBID),
            svc.get_album_info(MBID),
            return_exceptions=True,
        )

        assert all(isinstance(r, ResourceNotFoundError) for r in results)
        assert MBID not in svc._album_in_flight

    @pytest.mark.asyncio
    async def test_cache_hit_bypasses_singleflight(self):
        """Cache hit should not trigger _do_get_album_info at all."""
        svc = _make_service()
        fake = _fake_album_info()
        svc._get_cached_album_info = AsyncMock(return_value=fake)
        svc._apply_audiodb_album_images = AsyncMock(return_value=fake)
        call_count = 0

        async def should_not_run(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return fake

        svc._do_get_album_info = should_not_run

        result = await svc.get_album_info(MBID)
        assert result.title == "Test Album"
        assert call_count == 0

    @pytest.mark.asyncio
    async def test_different_ids_run_independently(self):
        """Different release_group_ids should run in parallel."""
        svc = _make_service()
        call_ids: list[str] = []

        async def tracking_fetch(rgid, *args, **kwargs):
            call_ids.append(rgid)
            await asyncio.sleep(0.02)
            return _fake_album_info()

        svc._do_get_album_info = tracking_fetch

        mbid_a = "aaaa1111-bbbb-cccc-dddd-eeeeeeeeeeee"
        mbid_b = "bbbb2222-bbbb-cccc-dddd-eeeeeeeeeeee"
        await asyncio.gather(
            svc.get_album_info(mbid_a),
            svc.get_album_info(mbid_b),
        )

        assert len(call_ids) == 2
        assert mbid_a in call_ids
        assert mbid_b in call_ids

    @pytest.mark.asyncio
    async def test_follower_cancellation_does_not_break_leader(self):
        """Cancelling a follower task must not poison the shared future."""
        svc = _make_service()
        gate = asyncio.Event()

        async def slow_fetch(*args, **kwargs):
            await gate.wait()
            return _fake_album_info()

        svc._do_get_album_info = slow_fetch

        leader_task = asyncio.create_task(svc.get_album_info(MBID))
        await asyncio.sleep(0)
        follower_task = asyncio.create_task(svc.get_album_info(MBID))
        await asyncio.sleep(0)

        follower_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await follower_task

        gate.set()
        result = await leader_task
        assert isinstance(result, AlbumInfo)
        assert MBID not in svc._album_in_flight

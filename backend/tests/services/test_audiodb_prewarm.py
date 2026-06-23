import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from repositories.audiodb_models import AudioDBArtistImages, AudioDBAlbumImages


TEST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
TEST_ALBUM_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"


def _make_settings(audiodb_enabled: bool = True, name_search_fallback: bool = False):
    s = MagicMock()
    s.audiodb_enabled = audiodb_enabled
    s.audiodb_name_search_fallback = name_search_fallback
    s.audiodb_prewarm_concurrency = 4
    s.audiodb_prewarm_delay = 0.0
    return s


def _make_prefs(settings=None):
    if settings is None:
        settings = _make_settings()
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = settings
    return prefs


def _make_status_service():
    status = MagicMock()
    status.update_phase = AsyncMock()
    status.update_progress = AsyncMock()
    status.persist_progress = AsyncMock()
    status.skip_phase = AsyncMock()
    status.is_cancelled.return_value = False
    return status


def _make_precache_service(audiodb_svc=None, prefs=None, cover_repo=None):
    from services.library_precache_service import LibraryPrecacheService

    if audiodb_svc is None:
        audiodb_svc = AsyncMock()
        audiodb_svc.get_cached_artist_images = AsyncMock(return_value=None)
        audiodb_svc.get_cached_album_images = AsyncMock(return_value=None)
        audiodb_svc.fetch_and_cache_artist_images = AsyncMock(return_value=None)
        audiodb_svc.fetch_and_cache_album_images = AsyncMock(return_value=None)
    if prefs is None:
        prefs = _make_prefs()
    if cover_repo is None:
        cover_repo = AsyncMock()
    return LibraryPrecacheService(
        library_repo=AsyncMock(),
        cover_repo=cover_repo,
        preferences_service=prefs,
        sync_state_store=AsyncMock(),
        genre_index=AsyncMock(),
        library_db=AsyncMock(),
        audiodb_image_service=audiodb_svc,
    )


class TestCheckAudioDBCacheNeeds:
    @pytest.mark.asyncio
    async def test_skips_cached_artists(self):
        svc = AsyncMock()
        images = AudioDBArtistImages(thumb_url="https://x.com/t.jpg", is_negative=False)
        svc.get_cached_artist_images = AsyncMock(return_value=images)
        svc.get_cached_album_images = AsyncMock(return_value=None)
        precache = _make_precache_service(audiodb_svc=svc)

        artists = [{"mbid": TEST_MBID, "name": "Coldplay"}]
        needed_artists, needed_albums = await precache._check_audiodb_cache_needs(artists, [])

        assert len(needed_artists) == 0

    @pytest.mark.asyncio
    async def test_includes_uncached_artists(self):
        svc = AsyncMock()
        svc.get_cached_artist_images = AsyncMock(return_value=None)
        svc.get_cached_album_images = AsyncMock(return_value=None)
        precache = _make_precache_service(audiodb_svc=svc)

        artists = [{"mbid": TEST_MBID, "name": "Coldplay"}]
        needed_artists, _ = await precache._check_audiodb_cache_needs(artists, [])

        assert len(needed_artists) == 1
        assert needed_artists[0]["mbid"] == TEST_MBID

    @pytest.mark.asyncio
    async def test_skips_unknown_mbid(self):
        svc = AsyncMock()
        svc.get_cached_artist_images = AsyncMock(return_value=None)
        precache = _make_precache_service(audiodb_svc=svc)

        artists = [{"mbid": "unknown_abc123", "name": "Unknown"}]
        needed_artists, _ = await precache._check_audiodb_cache_needs(artists, [])

        assert len(needed_artists) == 0


class TestPrecacheAudioDBData:
    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        settings = _make_settings(audiodb_enabled=False)
        prefs = _make_prefs(settings)
        svc = AsyncMock()
        precache = _make_precache_service(audiodb_svc=svc, prefs=prefs)

        status = _make_status_service()
        await precache._precache_audiodb_data(
            [{"mbid": TEST_MBID, "name": "Coldplay"}], [], status,
        )

        svc.fetch_and_cache_artist_images.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_when_all_cached(self):
        svc = AsyncMock()
        images = AudioDBArtistImages(thumb_url="https://x.com/t.jpg", is_negative=False)
        svc.get_cached_artist_images = AsyncMock(return_value=images)
        svc.get_cached_album_images = AsyncMock(return_value=images)
        precache = _make_precache_service(audiodb_svc=svc)

        status = _make_status_service()
        await precache._precache_audiodb_data(
            [{"mbid": TEST_MBID, "name": "Coldplay"}], [], status,
        )

        svc.fetch_and_cache_artist_images.assert_not_called()

    @pytest.mark.asyncio
    async def test_processes_uncached_artists(self):
        svc = AsyncMock()
        svc.get_cached_artist_images = AsyncMock(return_value=None)
        svc.get_cached_album_images = AsyncMock(return_value=None)
        result = AudioDBArtistImages(thumb_url="https://x.com/t.jpg", is_negative=False)
        svc.fetch_and_cache_artist_images = AsyncMock(return_value=result)
        precache = _make_precache_service(audiodb_svc=svc)

        status = _make_status_service()
        with patch.object(precache._audiodb_phase, 'download_bytes', new_callable=AsyncMock, return_value=True):
            await precache._precache_audiodb_data(
                [{"mbid": TEST_MBID, "name": "Coldplay"}], [], status,
            )

        svc.fetch_and_cache_artist_images.assert_called_once()

    @pytest.mark.asyncio
    async def test_respects_cancellation(self):
        svc = AsyncMock()
        svc.get_cached_artist_images = AsyncMock(return_value=None)
        svc.get_cached_album_images = AsyncMock(return_value=None)
        precache = _make_precache_service(audiodb_svc=svc)

        status = _make_status_service()
        status.is_cancelled.return_value = True

        await precache._precache_audiodb_data(
            [{"mbid": TEST_MBID, "name": "Coldplay"}], [], status,
        )

        svc.fetch_and_cache_artist_images.assert_not_called()


class TestSortByCoverPriority:
    def test_coverless_first(self, tmp_path):
        from repositories.coverart_disk_cache import get_cache_filename

        fake_cache_dir = tmp_path / "covers"
        fake_cache_dir.mkdir()

        cover_repo = MagicMock()
        cover_repo.cache_dir = fake_cache_dir
        precache = _make_precache_service(cover_repo=cover_repo)

        identifier_a = "artist_a_500"
        file_name = f"{get_cache_filename(identifier_a, 'img')}.bin"
        (fake_cache_dir / file_name).write_bytes(b"fake")

        artists = [
            {"mbid": "a", "name": "A"},
            {"mbid": "b", "name": "B"},
        ]
        sorted_list = precache._sort_by_cover_priority(artists, "artist")
        assert sorted_list[0]["mbid"] == "b"

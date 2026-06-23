import asyncio
import json
import time

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from api.v1.schemas.home import HomeGenre, HomeResponse, HomeSection
from services.home.genre_service import GenreService, GENRE_SECTION_TTL_DEFAULT


def _make_artist(mbid: str) -> MagicMock:
    a = MagicMock()
    a.musicbrainz_id = mbid
    return a


def _make_genre_service(
    tmp_path=None,
    genre_section_ttl: int = GENRE_SECTION_TTL_DEFAULT,
) -> tuple[GenreService, AsyncMock, AsyncMock]:
    mb = AsyncMock()
    mem_cache = AsyncMock()
    mem_cache.get = AsyncMock(return_value=None)
    mem_cache.set = AsyncMock()
    audiodb = AsyncMock()

    prefs = MagicMock()
    adv = MagicMock()
    adv.genre_section_ttl = genre_section_ttl
    prefs.get_advanced_settings.return_value = adv

    svc = GenreService(
        musicbrainz_repo=mb,
        memory_cache=mem_cache,
        audiodb_image_service=audiodb,
        cache_dir=tmp_path,
        preferences_service=prefs,
    )
    return svc, mb, mem_cache


class TestGenreSectionCacheHit:
    @pytest.mark.asyncio
    async def test_cache_hit_returns_data_no_mb_calls(self, tmp_path):
        svc, mb, mem_cache = _make_genre_service(tmp_path)
        genre_artists = {"rock": "mbid-1", "jazz": "mbid-2"}
        genre_images = {"rock": "http://img/rock.jpg", "jazz": "http://img/jazz.jpg"}

        mem_cache.get = AsyncMock(return_value=(genre_artists, genre_images))

        result = await svc.get_cached_genre_section("listenbrainz")
        assert result is not None
        assert result[0] == genre_artists
        assert result[1] == genre_images
        mb.search_artists_by_tag.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_cache_miss_returns_none(self, tmp_path):
        svc, _, mem_cache = _make_genre_service(tmp_path)
        mem_cache.get = AsyncMock(return_value=None)

        result = await svc.get_cached_genre_section("listenbrainz")
        assert result is None


class TestGenreSectionDiskPersistence:
    @pytest.mark.asyncio
    async def test_save_and_read_from_disk(self, tmp_path):
        svc, _, mem_cache = _make_genre_service(tmp_path)
        genre_artists = {"rock": "mbid-1", "pop": "mbid-2"}
        genre_images = {"rock": "http://img/rock.jpg"}

        await svc.save_genre_section("listenbrainz", genre_artists, genre_images)

        mem_cache.get = AsyncMock(return_value=None)
        result = await svc.get_cached_genre_section("listenbrainz")

        assert result is not None
        assert result[0] == genre_artists
        assert result[1] == genre_images

    @pytest.mark.asyncio
    async def test_disk_survives_memory_clear(self, tmp_path):
        # simulates a restart: fresh service, empty memory cache, data must come from disk
        svc, _, mem_cache = _make_genre_service(tmp_path)
        genre_artists = {"metal": "mbid-3"}
        genre_images = {"metal": "http://img/metal.jpg"}

        await svc.save_genre_section("lastfm", genre_artists, genre_images)

        mem_cache.get = AsyncMock(return_value=None)
        svc2, _, mem_cache2 = _make_genre_service(tmp_path)
        mem_cache2.get = AsyncMock(return_value=None)
        result = await svc2.get_cached_genre_section("lastfm")

        assert result is not None
        assert result[0] == genre_artists

    @pytest.mark.asyncio
    async def test_expired_disk_returns_none(self, tmp_path):
        svc, _, mem_cache = _make_genre_service(tmp_path, genre_section_ttl=1)
        genre_artists = {"rock": "mbid-1"}
        genre_images = {}

        await svc.save_genre_section("listenbrainz", genre_artists, genre_images)

        file_path = tmp_path / "genre_sections" / "listenbrainz.json"
        data = json.loads(file_path.read_text())
        data["built_at"] = time.time() - 100
        file_path.write_text(json.dumps(data))

        mem_cache.get = AsyncMock(return_value=None)
        result = await svc.get_cached_genre_section("listenbrainz")
        assert result is None


class TestGenreSectionBuild:
    @pytest.mark.asyncio
    async def test_build_caches_result(self, tmp_path):
        svc, mb, mem_cache = _make_genre_service(tmp_path)
        mb.search_artists_by_tag = AsyncMock(
            side_effect=lambda name, limit=10: [_make_artist(f"mbid-{name}")]
        )

        img_result = MagicMock()
        img_result.is_negative = False
        img_result.wide_thumb_url = "http://img/test.jpg"
        img_result.banner_url = None
        img_result.fanart_url = None
        svc._audiodb_image_service.fetch_and_cache_artist_images = AsyncMock(
            return_value=img_result
        )

        await svc.build_and_cache_genre_section("listenbrainz", ["rock", "jazz"])

        mem_cache.get = AsyncMock(return_value=None)
        result = await svc.get_cached_genre_section("listenbrainz")
        assert result is not None
        assert "rock" in result[0]
        assert "jazz" in result[0]

    @pytest.mark.asyncio
    async def test_build_skips_when_locked(self, tmp_path):
        # a build for a source already holding the lock is a no-op (no MB calls)
        svc, mb, _ = _make_genre_service(tmp_path)
        mb.search_artists_by_tag = AsyncMock(
            side_effect=lambda name, limit=10: [_make_artist(f"mbid-{name}")]
        )

        svc._genre_build_locks["listenbrainz"] = asyncio.Lock()
        async with svc._genre_build_locks["listenbrainz"]:
            await svc.build_and_cache_genre_section("listenbrainz", ["rock"])

        mb.search_artists_by_tag.assert_not_awaited()


class TestGenreSectionTTLSetting:
    @pytest.mark.asyncio
    async def test_ttl_from_preferences(self, tmp_path):
        svc, _, _ = _make_genre_service(tmp_path, genre_section_ttl=7200)
        assert svc._get_genre_section_ttl() == 7200

    @pytest.mark.asyncio
    async def test_ttl_default_on_missing(self, tmp_path):
        svc, _, _ = _make_genre_service(tmp_path)
        svc._preferences_service = None
        assert svc._get_genre_section_ttl() == GENRE_SECTION_TTL_DEFAULT


class TestAdvancedSettingsGenreTTL:
    def test_genre_section_ttl_default(self):
        from api.v1.schemas.advanced_settings import AdvancedSettings
        settings = AdvancedSettings()
        assert settings.genre_section_ttl == 21600

    def test_genre_section_ttl_roundtrip(self):
        from api.v1.schemas.advanced_settings import AdvancedSettings, AdvancedSettingsFrontend
        backend = AdvancedSettings(genre_section_ttl=43200)
        frontend = AdvancedSettingsFrontend.from_backend(backend)
        assert frontend.genre_section_ttl == 12
        roundtripped = frontend.to_backend()
        assert roundtripped.genre_section_ttl == 43200

    def test_genre_section_ttl_validation_rejects_below_minimum(self):
        from api.v1.schemas.advanced_settings import AdvancedSettings
        import msgspec
        with pytest.raises(msgspec.ValidationError):
            AdvancedSettings(genre_section_ttl=100)


class TestPerSourceLockIndependence:
    """Per-source locks allow parallel builds for different sources."""

    @pytest.mark.asyncio
    async def test_different_sources_build_independently(self, tmp_path):
        svc, mb, audiodb = _make_genre_service(tmp_path)
        mb.search_artists_by_tag = AsyncMock(
            side_effect=lambda name, limit=10: [_make_artist(f"mbid-{name}")]
        )
        audiodb.get_artist_images_batch = AsyncMock(return_value={})

        results = await asyncio.gather(
            svc.build_and_cache_genre_section("listenbrainz", ["rock"]),
            svc.build_and_cache_genre_section("lastfm", ["jazz"]),
        )

        assert mb.search_artists_by_tag.await_count == 2

    @pytest.mark.asyncio
    async def test_per_source_locks_created_on_demand(self, tmp_path):
        svc, mb, audiodb = _make_genre_service(tmp_path)

        assert "listenbrainz" not in svc._genre_build_locks

        mb.search_artists_by_tag = AsyncMock(
            side_effect=lambda name, limit=10: [_make_artist(f"mbid-{name}")]
        )
        audiodb.get_artist_images_batch = AsyncMock(return_value={})
        await svc.build_and_cache_genre_section("listenbrainz", ["rock"])

        assert "listenbrainz" in svc._genre_build_locks


class TestWarmerRetryOnNoop:
    """Warmer uses short retry interval when no sources were warmed."""

    @pytest.mark.asyncio
    async def test_warmer_retries_quickly_on_no_data(self):
        # with no library genres the warmer retries after 60s, not the full TTL
        from core.tasks import warm_genre_cache_periodically

        home_svc = AsyncMock()
        home_svc.get_library_genre_names = AsyncMock(return_value=[])
        home_svc._genre._get_genre_section_ttl = MagicMock(return_value=21600)

        sleep_values: list[int | float] = []
        call_count = 0

        original_sleep = asyncio.sleep

        async def mock_sleep(seconds):
            nonlocal call_count
            sleep_values.append(seconds)
            call_count += 1
            if call_count >= 2:
                raise asyncio.CancelledError
            return await original_sleep(0)

        with patch("core.tasks.asyncio.sleep", side_effect=mock_sleep):
            try:
                await warm_genre_cache_periodically(home_svc, interval=21600)
            except asyncio.CancelledError:
                pass

        assert len(sleep_values) >= 2
        assert sleep_values[1] == 60

"""Tests for skipping Lidarr when not configured (no API key)."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from core.config import Settings
from core.exceptions import ExternalServiceError


@pytest.fixture
def unconfigured_settings():
    settings = MagicMock(spec=Settings)
    settings.lidarr_url = "http://lidarr:8686"
    settings.lidarr_api_key = ""
    return settings


@pytest.fixture
def configured_settings():
    settings = MagicMock(spec=Settings)
    settings.lidarr_url = "http://lidarr:8686"
    settings.lidarr_api_key = "test-api-key-123"
    return settings


class TestLidarrBaseIsConfigured:
    def test_not_configured_when_api_key_empty(self, unconfigured_settings):
        from repositories.lidarr.base import LidarrBase

        base = LidarrBase(unconfigured_settings, MagicMock(), MagicMock())
        assert base.is_configured() is False

    def test_configured_when_api_key_set(self, configured_settings):
        from repositories.lidarr.base import LidarrBase

        base = LidarrBase(configured_settings, MagicMock(), MagicMock())
        assert base.is_configured() is True


class TestLidarrRequestGuard:
    @pytest.mark.asyncio
    async def test_request_raises_when_not_configured(self, unconfigured_settings):
        from repositories.lidarr.base import LidarrBase

        base = LidarrBase(unconfigured_settings, MagicMock(), MagicMock())
        with pytest.raises(ExternalServiceError, match="not configured"):
            await base._request("GET", "/api/v1/album")


class TestAlbumServiceSkipsLidarr:
    @pytest.mark.asyncio
    async def test_basic_info_skips_lidarr_when_unconfigured(self):
        """When Lidarr is not configured, get_album_basic_info must not call any Lidarr methods."""
        from services.album_service import AlbumService

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False
        lidarr.get_requested_mbids = AsyncMock()
        lidarr.get_album_details = AsyncMock()

        mb_repo = MagicMock()
        mb_repo.get_release_group_by_id = AsyncMock(return_value={
            "id": "f50a3b6f-27f0-3832-bd3f-3568dc557d95",
            "title": "Beatles for Sale",
            "primary-type": "Album",
            "artist-credit": [{"artist": {"id": "b10bbbfc-cf9e-42e0-be17-e2c3e1d2600d", "name": "The Beatles"}}],
            "first-release-date": "1964-12-04",
            "releases": [],
        })
        mb_repo.get_release_group = mb_repo.get_release_group_by_id

        memory_cache = AsyncMock()
        memory_cache.get.return_value = None
        disk_cache = AsyncMock()
        disk_cache.get_album.return_value = None
        library_db = AsyncMock()
        library_db.get_album_by_mbid.return_value = None
        prefs = MagicMock()
        prefs.get_advanced_settings.return_value = MagicMock(
            cache_ttl_album_library=86400,
            cache_ttl_album_non_library=86400,
        )
        audiodb_svc = MagicMock()
        audiodb_svc.fetch_and_cache_album_thumb = AsyncMock(return_value=None)
        audiodb_svc.fetch_and_cache_album_images = AsyncMock(return_value=None)

        svc = AlbumService(
            lidarr_repo=lidarr,
            mb_repo=mb_repo,
            memory_cache=memory_cache,
            disk_cache=disk_cache,
            library_db=library_db,
            preferences_service=prefs,
            audiodb_image_service=audiodb_svc,
        )

        result = await svc.get_album_basic_info("f50a3b6f-27f0-3832-bd3f-3568dc557d95")

        lidarr.get_requested_mbids.assert_not_called()
        lidarr.get_album_details.assert_not_called()
        assert result.title == "Beatles for Sale"
        assert result.artist_name == "The Beatles"


class TestCoverArtSkipsLidarr:
    @pytest.mark.asyncio
    async def test_album_cover_skips_lidarr_when_unconfigured(self):
        from repositories.coverart_album import AlbumCoverFetcher
        from pathlib import Path

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False
        lidarr.get_album_image_url = AsyncMock()

        fetcher = AlbumCoverFetcher.__new__(AlbumCoverFetcher)
        fetcher._lidarr_repo = lidarr

        result = await fetcher._fetch_from_lidarr("test-id", Path("/tmp/test"), size=500)

        assert result is None
        lidarr.get_album_image_url.assert_not_called()

    @pytest.mark.asyncio
    async def test_artist_cover_skips_lidarr_when_unconfigured(self):
        from repositories.coverart_artist import ArtistImageFetcher
        from pathlib import Path

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False
        lidarr.get_artist_image_url = AsyncMock()

        fetcher = ArtistImageFetcher.__new__(ArtistImageFetcher)
        fetcher._lidarr_repo = lidarr

        result = await fetcher._fetch_from_lidarr("test-id", None, Path("/tmp/test"))

        assert result is None
        lidarr.get_artist_image_url.assert_not_called()


class TestRequestServiceSkipsLidarr:
    @pytest.mark.asyncio
    async def test_request_album_raises_when_unconfigured(self):
        from services.request_service import RequestService

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False

        svc = RequestService(lidarr, MagicMock(), MagicMock())

        with pytest.raises(ExternalServiceError, match="isn.t configured"):
            await svc.request_album("test-mbid", user_role="admin")


class TestLibraryServiceSkipsLidarr:
    @pytest.mark.asyncio
    async def test_get_library_mbids_returns_empty_when_unconfigured(self):
        from services.library_service import LibraryService

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False

        svc = LibraryService.__new__(LibraryService)
        svc._lidarr_repo = lidarr

        result = await svc.get_library_mbids()
        assert result == []

    @pytest.mark.asyncio
    async def test_get_requested_mbids_returns_empty_when_unconfigured(self):
        from services.library_service import LibraryService

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False

        svc = LibraryService.__new__(LibraryService)
        svc._lidarr_repo = lidarr

        result = await svc.get_requested_mbids()
        assert result == []

    @pytest.mark.asyncio
    async def test_sync_library_raises_when_unconfigured(self):
        from services.library_service import LibraryService

        lidarr = MagicMock()
        lidarr.is_configured.return_value = False

        svc = LibraryService.__new__(LibraryService)
        svc._lidarr_repo = lidarr

        with pytest.raises(ExternalServiceError, match="not configured"):
            await svc.sync_library()

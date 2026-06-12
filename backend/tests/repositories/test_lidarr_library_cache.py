import asyncio
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

import httpx

from core.config import Settings
from infrastructure.cache.memory_cache import InMemoryCache
from infrastructure.cache.cache_keys import lidarr_library_mbids_key, lidarr_raw_albums_key
from repositories.lidarr.base import LIDARR_LIBRARY_SCAN_TTL_SECONDS
from repositories.lidarr.library import LidarrLibraryRepository


def _make_settings() -> Settings:
    settings = MagicMock(spec=Settings)
    settings.lidarr_url = "http://localhost:8686"
    settings.lidarr_api_key = "test-key"
    return settings


def _sample_album_data() -> list[dict]:
    return [
        {
            "id": 1,
            "title": "Album One",
            "foreignAlbumId": "aaaa-bbbb-cccc",
            "monitored": True,
            "releaseDate": "2023-01-15",
            "added": "2023-01-10T12:00:00Z",
            "images": [],
            "statistics": {"trackFileCount": 5},
            "artist": {
                "artistName": "Artist A",
                "foreignArtistId": "artist-a-mbid",
            },
        },
        {
            "id": 2,
            "title": "Album Two",
            "foreignAlbumId": "dddd-eeee-ffff",
            "monitored": True,
            "releaseDate": "2024-06-01",
            "added": "2024-06-01T08:00:00Z",
            "images": [],
            "statistics": {"trackFileCount": 8},
            "artist": {
                "artistName": "Artist B",
                "foreignArtistId": "artist-b-mbid",
            },
        },
        {
            "id": 3,
            "title": "Unmonitored Album",
            "foreignAlbumId": "1111-2222-3333",
            "monitored": False,
            "releaseDate": "2020-03-01",
            "added": "2020-03-01T00:00:00Z",
            "images": [],
            "statistics": {"trackFileCount": 3},
            "artist": {
                "artistName": "Artist C",
                "foreignArtistId": "artist-c-mbid",
            },
        },
    ]


@pytest.fixture
def cache():
    return InMemoryCache(max_entries=100)


@pytest.fixture
def repo(cache):
    settings = _make_settings()
    http_client = AsyncMock(spec=httpx.AsyncClient)
    return LidarrLibraryRepository(settings=settings, http_client=http_client, cache=cache)


class TestGetLibraryCache:
    @pytest.mark.asyncio
    async def test_get_library_caches_result(self, repo):
        """Second call should return cached result without hitting the API."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _sample_album_data()

            first = await repo.get_library()
            second = await repo.get_library()

            assert mock_get.await_count == 1
            assert len(first) == 2
            assert first == second

    @pytest.mark.asyncio
    async def test_get_library_separate_cache_keys_for_unmonitored(self, repo):
        """include_unmonitored=True and False use different cache keys."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _sample_album_data()

            monitored_only = await repo.get_library(include_unmonitored=False)
            all_albums = await repo.get_library(include_unmonitored=True)

            assert mock_get.await_count == 1
            assert len(monitored_only) == 2
            assert len(all_albums) == 3


class TestGetArtistsFromLibraryCache:
    @pytest.mark.asyncio
    async def test_get_artists_caches_result(self, repo):
        """Second call should return cached result without hitting the API."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _sample_album_data()

            first = await repo.get_artists_from_library()
            second = await repo.get_artists_from_library()

            assert mock_get.await_count == 1
            assert len(first) == 2
            assert first == second

    @pytest.mark.asyncio
    async def test_get_artists_separate_cache_keys_for_unmonitored(self, repo):
        """include_unmonitored=True and False use different cache keys."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _sample_album_data()

            monitored_only = await repo.get_artists_from_library(include_unmonitored=False)
            all_artists = await repo.get_artists_from_library(include_unmonitored=True)

            assert mock_get.await_count == 1
            assert len(monitored_only) == 2
            assert len(all_artists) == 3


class TestCacheInvalidation:
    @pytest.mark.asyncio
    async def test_clear_prefix_invalidates_derived_but_keeps_raw_cache(self, repo, cache):
        """Clearing library prefix should invalidate derived keys while reusing the raw shared cache."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _sample_album_data()

            await repo.get_library()
            await repo.get_artists_from_library()
            assert mock_get.await_count == 1

            await cache.clear_prefix("lidarr:library:")

            await repo.get_library()
            await repo.get_artists_from_library()
            assert mock_get.await_count == 1


class TestSharedRawAlbumCache:
    @pytest.mark.asyncio
    async def test_library_mbids_and_raw_albums_use_long_scan_ttl(self, repo, cache):
        """Full-library Lidarr scans should stay warm beyond a short page visit cache."""
        original_set = cache.set
        cache_set_calls: list[tuple[str, int]] = []

        async def record_set(key, value, ttl_seconds=60):
            cache_set_calls.append((key, ttl_seconds))
            await original_set(key, value, ttl_seconds=ttl_seconds)

        cache.set = AsyncMock(side_effect=record_set)

        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {
                    "foreignAlbumId": "aaaa",
                    "statistics": {"trackFileCount": 10},
                    "releases": [{"foreignId": "release-aaaa"}],
                },
            ]

            result = await repo.get_library_mbids(include_release_ids=True)

        assert result == {"aaaa", "release-aaaa"}
        ttl_by_key = {key: ttl for key, ttl in cache_set_calls}
        assert ttl_by_key[lidarr_raw_albums_key()] == LIDARR_LIBRARY_SCAN_TTL_SECONDS
        assert ttl_by_key[lidarr_library_mbids_key(True)] == LIDARR_LIBRARY_SCAN_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_concurrent_mbids_calls_deduplicate_raw_album_fetch(self, repo):
        """Concurrent MBID calls should coalesce to one /api/v1/album request."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = [
                {
                    "foreignAlbumId": "aaaa",
                    "monitored": True,
                    "statistics": {"trackFileCount": 10},
                    "releases": [],
                },
                {
                    "foreignAlbumId": "bbbb",
                    "monitored": True,
                    "statistics": {"trackFileCount": 0},
                    "releases": [],
                },
            ]

            library_mbids, monitored_no_files = await asyncio.gather(
                repo.get_library_mbids(include_release_ids=False),
                repo.get_monitored_no_files_mbids(),
            )

            assert mock_get.await_count == 1
            assert library_mbids == {"aaaa"}
            assert monitored_no_files == {"bbbb"}

    @pytest.mark.asyncio
    async def test_get_requested_mbids_uses_history_store(self, repo):
        """get_requested_mbids delegates to RequestHistoryStore."""
        mock_store = AsyncMock()
        mock_store.async_get_active_mbids = AsyncMock(return_value={"cccc", "dddd"})
        repo._request_history_store = mock_store

        result = await repo.get_requested_mbids()
        assert result == {"cccc", "dddd"}
        mock_store.async_get_active_mbids.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_get_requested_mbids_returns_empty_without_store(self, repo):
        """get_requested_mbids returns empty set when no history store."""
        repo._request_history_store = None
        result = await repo.get_requested_mbids()
        assert result == set()

    @pytest.mark.asyncio
    async def test_explicit_album_cache_invalidation_forces_refetch(self, repo):
        """Base helper should clear raw cache so next read refetches /api/v1/album."""
        with patch.object(repo, "_get", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = _sample_album_data()

            await repo.get_library()
            assert mock_get.await_count == 1

            await repo._invalidate_album_list_caches()
            await repo.get_library()
            assert mock_get.await_count == 2

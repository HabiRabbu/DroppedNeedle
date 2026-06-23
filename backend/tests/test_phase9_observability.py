"""Phase 9 observability contract tests.

Verifies SSE / cache-stats wiring propagates AudioDB data end-to-end.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import msgspec
import pytest

from repositories.audiodb_models import (
    AudioDBArtistImages,
    AudioDBArtistResponse,
    AudioDBAlbumImages,
    AudioDBAlbumResponse,
)
from services.audiodb_image_service import AudioDBImageService

TEST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
TEST_ALBUM_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"

SAMPLE_ARTIST_RESP = AudioDBArtistResponse(
    idArtist="111239",
    strArtist="Coldplay",
    strMusicBrainzID=TEST_MBID,
    strArtistThumb="https://example.com/thumb.jpg",
    strArtistFanart="https://example.com/fanart.jpg",
)

SAMPLE_ALBUM_RESP = AudioDBAlbumResponse(
    idAlbum="2115888",
    strAlbum="Parachutes",
    strMusicBrainzID=TEST_ALBUM_MBID,
    strAlbumThumb="https://example.com/album_thumb.jpg",
    strAlbumBack="https://example.com/album_back.jpg",
)


def _make_settings(enabled=True, name_search_fallback=False):
    s = MagicMock()
    s.audiodb_enabled = enabled
    s.audiodb_name_search_fallback = name_search_fallback
    s.cache_ttl_audiodb_found = 604800
    s.cache_ttl_audiodb_not_found = 86400
    s.cache_ttl_audiodb_library = 1209600
    s.audiodb_prewarm_concurrency = 4
    s.audiodb_prewarm_delay = 0.0
    return s


def _make_image_service(settings=None, disk_cache=None, repo=None):
    if settings is None:
        settings = _make_settings()
    prefs = MagicMock()
    prefs.get_advanced_settings.return_value = settings
    if disk_cache is None:
        disk_cache = AsyncMock()
        disk_cache.get_audiodb_artist = AsyncMock(return_value=None)
        disk_cache.get_audiodb_album = AsyncMock(return_value=None)
        disk_cache.set_audiodb_artist = AsyncMock()
        disk_cache.set_audiodb_album = AsyncMock()
    if repo is None:
        repo = AsyncMock()
    return AudioDBImageService(
        audiodb_repo=repo,
        disk_cache=disk_cache,
        preferences_service=prefs,
    )


class TestPrewarmLogContract:
    def _make_status_service(self):
        status = MagicMock()
        status.update_phase = AsyncMock()
        status.update_progress = AsyncMock()
        status.persist_progress = AsyncMock()
        status.is_cancelled.return_value = False
        return status

    def _make_precache_service(self, audiodb_svc=None, prefs=None):
        from services.library_precache_service import LibraryPrecacheService

        if audiodb_svc is None:
            audiodb_svc = AsyncMock()
            audiodb_svc.get_cached_artist_images = AsyncMock(return_value=None)
            audiodb_svc.get_cached_album_images = AsyncMock(return_value=None)
            audiodb_svc.fetch_and_cache_artist_images = AsyncMock(return_value=None)
            audiodb_svc.fetch_and_cache_album_images = AsyncMock(return_value=None)
        if prefs is None:
            settings = MagicMock()
            settings.audiodb_enabled = True
            settings.audiodb_name_search_fallback = False
            settings.audiodb_prewarm_concurrency = 4
            settings.audiodb_prewarm_delay = 0.0
            prefs = MagicMock()
            prefs.get_advanced_settings.return_value = settings
        return LibraryPrecacheService(
            library_repo=AsyncMock(),
            cover_repo=AsyncMock(),
            preferences_service=prefs,
            sync_state_store=AsyncMock(),
            genre_index=AsyncMock(),
            library_db=AsyncMock(),
            audiodb_image_service=audiodb_svc,
        )

    @pytest.mark.asyncio
    async def test_prewarm_calls_update_phase_audiodb(self):
        svc = AsyncMock()
        svc.get_cached_artist_images = AsyncMock(return_value=None)
        svc.get_cached_album_images = AsyncMock(return_value=None)
        svc.fetch_and_cache_artist_images = AsyncMock(return_value=None)

        precache = self._make_precache_service(audiodb_svc=svc)
        status = self._make_status_service()

        artists = [{"mbid": TEST_MBID, "name": "Coldplay"}]
        await precache._precache_audiodb_data(artists, [], status)

        phase_calls = [
            c for c in status.update_phase.call_args_list
            if c.args[0] == "audiodb_prewarm"
        ]
        assert len(phase_calls) >= 1, "Expected update_phase('audiodb_prewarm', ...) call"




class TestCacheStatsAudioDBWiring:
    @pytest.mark.asyncio
    async def test_get_stats_includes_audiodb_counts(self):
        from services.cache_service import CacheService

        disk_cache = MagicMock()
        disk_cache.get_stats.return_value = {
            "total_count": 100,
            "album_count": 60,
            "artist_count": 40,
            "audiodb_artist_count": 15,
            "audiodb_album_count": 25,
        }

        mem_cache = MagicMock()
        mem_cache.size.return_value = 10
        mem_cache.estimate_memory_bytes.return_value = 2048

        library_db = AsyncMock()
        library_db.get_stats = AsyncMock(return_value={
            "artist_count": 5,
            "album_count": 8,
            "db_size_bytes": 4096,
        })

        svc = CacheService(
            cache=mem_cache,
            library_db=library_db,
            disk_cache=disk_cache,
        )
        svc._stats_cache_ttl = 0

        with patch("services.cache_service.get_covers_cache_dir") as mock_get_dir:
            mock_dir = MagicMock()
            mock_dir.exists.return_value = False
            mock_get_dir.return_value = mock_dir
            stats = await svc.get_stats()

        assert stats.disk_audiodb_artist_count == 15
        assert stats.disk_audiodb_album_count == 25

"""Integration-level tests for the artist/album detail → AudioDB enrichment flows.

Covers the critical paths identified in Phase 3 peer review:
- Cached artist/album objects still receive AudioDB enrichment (allow_fetch=True)
- Album basic info endpoint performs on-demand AudioDB fetch
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from api.v1.schemas.artist import ArtistInfo
from api.v1.schemas.album import AlbumInfo, AlbumBasicInfo
from repositories.audiodb_models import AudioDBArtistImages, AudioDBAlbumImages
from services.artist_service import ArtistService
from services.album_service import AlbumService


TEST_ARTIST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
TEST_ALBUM_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"

ARTIST_IMAGES = AudioDBArtistImages(
    thumb_url="https://cdn.example.com/thumb.jpg",
    fanart_url="https://cdn.example.com/fanart1.jpg",
    fanart_url_2="https://cdn.example.com/fanart2.jpg",
    fanart_url_3=None,
    fanart_url_4=None,
    wide_thumb_url=None,
    banner_url="https://cdn.example.com/banner.jpg",
    logo_url=None,
    clearart_url=None,
    cutout_url=None,
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)

ALBUM_IMAGES = AudioDBAlbumImages(
    album_thumb_url="https://cdn.example.com/album_thumb.jpg",
    album_back_url=None,
    album_cdart_url=None,
    album_spine_url=None,
    album_3d_case_url=None,
    album_3d_flat_url=None,
    album_3d_face_url=None,
    album_3d_thumb_url=None,
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)


def _cached_artist(**overrides) -> ArtistInfo:
    defaults = dict(name="Coldplay", musicbrainz_id=TEST_ARTIST_MBID, in_library=True)
    defaults.update(overrides)
    return ArtistInfo(**defaults)


def _cached_album(**overrides) -> AlbumInfo:
    defaults = dict(
        title="Parachutes",
        musicbrainz_id=TEST_ALBUM_MBID,
        artist_name="Coldplay",
        artist_id=TEST_ARTIST_MBID,
        in_library=False,
    )
    defaults.update(overrides)
    return AlbumInfo(**defaults)


def _artist_service(audiodb=None) -> ArtistService:
    if audiodb is None:
        audiodb = MagicMock()
    prefs = MagicMock()
    adv = MagicMock()
    adv.cache_ttl_artist_library = 86400
    adv.cache_ttl_artist_non_library = 3600
    prefs.get_advanced_settings.return_value = adv
    return ArtistService(
        mb_repo=MagicMock(),
        library_repo=MagicMock(),
        wikidata_repo=MagicMock(),
        preferences_service=prefs,
        memory_cache=MagicMock(),
        disk_cache=MagicMock(),
        audiodb_image_service=audiodb,
    )


def _album_service(audiodb=None) -> AlbumService:
    if audiodb is None:
        audiodb = MagicMock()
    prefs = MagicMock()
    adv = MagicMock()
    adv.cache_ttl_album_library = 86400
    adv.cache_ttl_album_non_library = 3600
    prefs.get_advanced_settings.return_value = adv
    return AlbumService(
        library_repo=MagicMock(),
        mb_repo=MagicMock(),
        library_db=MagicMock(),
        memory_cache=MagicMock(),
        disk_cache=MagicMock(),
        preferences_service=prefs,
        audiodb_image_service=audiodb,
    )


class TestArtistDetailCacheHitEnrichment:
    """get_artist_info() must apply AudioDB images from cache on cache hit."""

    @pytest.mark.asyncio
    async def test_cached_artist_gets_audiodb_enrichment(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        svc = _artist_service(audiodb)
        cached = _cached_artist()
        svc._cache = MagicMock()
        svc._cache.get = AsyncMock(return_value=cached)

        result = await svc.get_artist_info(TEST_ARTIST_MBID)

        assert result.thumb_url == "https://cdn.example.com/thumb.jpg"
        assert result.fanart_url == "https://cdn.example.com/fanart1.jpg"
        assert result.fanart_url_2 == "https://cdn.example.com/fanart2.jpg"
        audiodb.get_cached_artist_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_artist_preserves_existing_fanart(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        svc = _artist_service(audiodb)
        cached = _cached_artist(fanart_url="https://library.example.com/fanart.jpg")
        svc._cache = MagicMock()
        svc._cache.get = AsyncMock(return_value=cached)

        result = await svc.get_artist_info(TEST_ARTIST_MBID)

        assert result.fanart_url == "https://library.example.com/fanart.jpg"
        assert result.thumb_url == "https://cdn.example.com/thumb.jpg"

    @pytest.mark.asyncio
    async def test_cached_artist_audiodb_failure_returns_cached(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(side_effect=RuntimeError("unavailable"))
        svc = _artist_service(audiodb)
        cached = _cached_artist()
        svc._cache = MagicMock()
        svc._cache.get = AsyncMock(return_value=cached)

        result = await svc.get_artist_info(TEST_ARTIST_MBID)

        assert result.name == "Coldplay"
        assert result.thumb_url is None


class TestAlbumDetailCacheHitEnrichment:
    """get_album_info() must apply AudioDB images even on cache hit."""

    @pytest.mark.asyncio
    async def test_cached_album_gets_audiodb_enrichment(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _album_service(audiodb)
        cached = _cached_album()
        svc._get_cached_album_info = AsyncMock(return_value=cached)

        result = await svc.get_album_info(TEST_ALBUM_MBID)

        assert result.album_thumb_url == "https://cdn.example.com/album_thumb.jpg"
        audiodb.fetch_and_cache_album_images.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_cached_album_audiodb_failure_returns_cached(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(side_effect=RuntimeError("unavailable"))
        svc = _album_service(audiodb)
        cached = _cached_album()
        svc._get_cached_album_info = AsyncMock(return_value=cached)

        result = await svc.get_album_info(TEST_ALBUM_MBID)

        assert result.title == "Parachutes"
        assert result.album_thumb_url is None


class TestAlbumBasicInfoOnDemandFetch:
    """get_album_basic_info() applies cached AudioDB images (no network fetch on critical path)."""

    @pytest.mark.asyncio
    async def test_basic_info_cache_hit_fetches_audiodb_thumb(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _album_service(audiodb)
        cached = _cached_album(album_thumb_url=None)
        svc._get_cached_album_info = AsyncMock(return_value=cached)
        svc._library_repo.get_requested_mbids = AsyncMock(return_value=set())

        result = await svc.get_album_basic_info(TEST_ALBUM_MBID)

        assert result.album_thumb_url == "https://cdn.example.com/album_thumb.jpg"
        audiodb.get_cached_album_images.assert_awaited_once_with(TEST_ALBUM_MBID)

    @pytest.mark.asyncio
    async def test_basic_info_cache_hit_keeps_existing_thumb(self):
        audiodb = MagicMock()
        svc = _album_service(audiodb)
        cached = _cached_album(album_thumb_url="https://existing.example.com/thumb.jpg")
        svc._get_cached_album_info = AsyncMock(return_value=cached)
        svc._library_repo.get_requested_mbids = AsyncMock(return_value=set())

        result = await svc.get_album_basic_info(TEST_ALBUM_MBID)

        assert result.album_thumb_url == "https://existing.example.com/thumb.jpg"
        audiodb.fetch_and_cache_album_images.assert_not_called()

    @pytest.mark.asyncio
    async def test_basic_info_audiodb_failure_returns_none_thumb(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(side_effect=RuntimeError("boom"))
        svc = _album_service(audiodb)
        cached = _cached_album(album_thumb_url=None)
        svc._get_cached_album_info = AsyncMock(return_value=cached)
        svc._library_repo.get_requested_mbids = AsyncMock(return_value=set())

        result = await svc.get_album_basic_info(TEST_ALBUM_MBID)

        assert result.album_thumb_url is None
        assert result.title == "Parachutes"

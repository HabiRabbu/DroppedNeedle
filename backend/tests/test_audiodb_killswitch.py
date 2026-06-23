"""Regression: audiodb_enabled=False suppresses all AudioDB behavior, via both
the settings short-circuit and the audiodb_service=None DI null-guard."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.album import AlbumInfo
from api.v1.schemas.artist import ArtistInfo
from api.v1.schemas.search import SearchResult
from repositories.audiodb_models import AudioDBArtistImages, AudioDBAlbumImages
from repositories.audiodb_repository import AudioDBRepository
from repositories.coverart_album import AlbumCoverFetcher
from services.audiodb_image_service import AudioDBImageService
from services.album_service import AlbumService
from services.artist_service import ArtistService
from services.search_service import SearchService

TEST_ARTIST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
TEST_ALBUM_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"

ARTIST_IMAGES = AudioDBArtistImages(
    thumb_url="https://cdn.example.com/thumb.jpg",
    fanart_url="https://cdn.example.com/fanart1.jpg",
    fanart_url_2="https://cdn.example.com/fanart2.jpg",
    fanart_url_3="https://cdn.example.com/fanart3.jpg",
    fanart_url_4="https://cdn.example.com/fanart4.jpg",
    wide_thumb_url="https://cdn.example.com/wide.jpg",
    banner_url="https://cdn.example.com/banner.jpg",
    logo_url="https://cdn.example.com/logo.png",
    clearart_url="https://cdn.example.com/clearart.png",
    cutout_url="https://cdn.example.com/cutout.png",
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)

ALBUM_IMAGES = AudioDBAlbumImages(
    album_thumb_url="https://cdn.example.com/album_thumb.jpg",
    album_back_url="https://cdn.example.com/album_back.jpg",
    album_cdart_url="https://cdn.example.com/album_cdart.png",
    album_spine_url="https://cdn.example.com/album_spine.jpg",
    album_3d_case_url="https://cdn.example.com/3d_case.png",
    album_3d_flat_url="https://cdn.example.com/3d_flat.png",
    album_3d_face_url="https://cdn.example.com/3d_face.png",
    album_3d_thumb_url="https://cdn.example.com/3d_thumb.png",
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)


ARTIST_IMAGES_RAW = {
    "thumb_url": ARTIST_IMAGES.thumb_url,
    "fanart_url": ARTIST_IMAGES.fanart_url,
    "fanart_url_2": ARTIST_IMAGES.fanart_url_2,
    "fanart_url_3": ARTIST_IMAGES.fanart_url_3,
    "fanart_url_4": ARTIST_IMAGES.fanart_url_4,
    "wide_thumb_url": ARTIST_IMAGES.wide_thumb_url,
    "banner_url": ARTIST_IMAGES.banner_url,
    "logo_url": ARTIST_IMAGES.logo_url,
    "clearart_url": ARTIST_IMAGES.clearart_url,
    "cutout_url": ARTIST_IMAGES.cutout_url,
    "lookup_source": "mbid",
    "is_negative": False,
    "cached_at": 1000.0,
}

ALBUM_IMAGES_RAW = {
    "album_thumb_url": ALBUM_IMAGES.album_thumb_url,
    "album_back_url": ALBUM_IMAGES.album_back_url,
    "album_cdart_url": ALBUM_IMAGES.album_cdart_url,
    "album_spine_url": ALBUM_IMAGES.album_spine_url,
    "album_3d_case_url": ALBUM_IMAGES.album_3d_case_url,
    "album_3d_flat_url": ALBUM_IMAGES.album_3d_flat_url,
    "album_3d_face_url": ALBUM_IMAGES.album_3d_face_url,
    "album_3d_thumb_url": ALBUM_IMAGES.album_3d_thumb_url,
    "lookup_source": "mbid",
    "is_negative": False,
    "cached_at": 1000.0,
}



def _make_artist_info(**overrides) -> ArtistInfo:
    defaults = dict(name="Coldplay", musicbrainz_id=TEST_ARTIST_MBID)
    defaults.update(overrides)
    return ArtistInfo(**defaults)


def _make_album_info(**overrides) -> AlbumInfo:
    defaults = dict(
        title="Parachutes",
        musicbrainz_id=TEST_ALBUM_MBID,
        artist_name="Coldplay",
        artist_id=TEST_ARTIST_MBID,
    )
    defaults.update(overrides)
    return AlbumInfo(**defaults)


def _disabled_settings() -> MagicMock:
    prefs = MagicMock()
    settings = MagicMock()
    settings.audiodb_enabled = False
    prefs.get_advanced_settings.return_value = settings
    return prefs


def _disabled_image_service() -> AudioDBImageService:
    disk_cache = MagicMock()
    disk_cache.get_audiodb_artist = AsyncMock(return_value=ARTIST_IMAGES_RAW)
    disk_cache.get_audiodb_album = AsyncMock(return_value=ALBUM_IMAGES_RAW)
    return AudioDBImageService(
        audiodb_repo=MagicMock(),
        disk_cache=disk_cache,
        preferences_service=_disabled_settings(),
        memory_cache=None,
    )


def _make_artist_service(audiodb_service=None) -> ArtistService:
    return ArtistService(
        mb_repo=MagicMock(),
        library_repo=MagicMock(),
        wikidata_repo=MagicMock(),
        preferences_service=MagicMock(),
        memory_cache=MagicMock(),
        disk_cache=MagicMock(),
        audiodb_image_service=audiodb_service,
    )


def _make_album_service(audiodb_service=None) -> AlbumService:
    return AlbumService(
        library_repo=MagicMock(),
        mb_repo=MagicMock(),
        library_db=MagicMock(),
        memory_cache=MagicMock(),
        disk_cache=MagicMock(),
        preferences_service=MagicMock(),
        audiodb_image_service=audiodb_service,
    )


def _make_search_service(audiodb_service=None) -> SearchService:
    mb_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_mbids = AsyncMock(return_value=set())
    coverart_repo = MagicMock()
    prefs = MagicMock()
    prefs.get_preferences.return_value = MagicMock(secondary_types=[])
    return SearchService(mb_repo, library_repo, coverart_repo, prefs, audiodb_service)


def _make_repo(enabled: bool = True) -> AudioDBRepository:
    client = AsyncMock()
    prefs = MagicMock()
    settings = MagicMock()
    settings.audiodb_enabled = enabled
    settings.audiodb_api_key = "test_key"
    prefs.get_advanced_settings.return_value = settings
    return AudioDBRepository(
        http_client=client,
        preferences_service=prefs,
        api_key="test_key",
        premium=False,
    )


class TestSettingsKillSwitchArtist:
    """8.10.a"""

    @pytest.mark.asyncio
    async def test_image_service_returns_none_despite_cached_data(self):
        img_svc = _disabled_image_service()
        result = await img_svc.get_cached_artist_images(TEST_ARTIST_MBID)
        assert result is None
        img_svc._disk_cache.get_audiodb_artist.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_fetch_returns_none_despite_cached_data(self):
        img_svc = _disabled_image_service()
        result = await img_svc.fetch_and_cache_artist_images(TEST_ARTIST_MBID, "Coldplay")
        assert result is None

    @pytest.mark.asyncio
    async def test_artist_detail_all_audiodb_fields_none(self):
        img_svc = _disabled_image_service()
        svc = _make_artist_service(audiodb_service=img_svc)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_ARTIST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.thumb_url is None
        assert result.fanart_url_2 is None
        assert result.fanart_url_3 is None
        assert result.fanart_url_4 is None
        assert result.wide_thumb_url is None
        assert result.logo_url is None
        assert result.clearart_url is None
        assert result.cutout_url is None


class TestSettingsKillSwitchAlbum:
    """8.10.b"""

    @pytest.mark.asyncio
    async def test_image_service_returns_none_despite_cached_data(self):
        img_svc = _disabled_image_service()
        result = await img_svc.get_cached_album_images(TEST_ALBUM_MBID)
        assert result is None
        img_svc._disk_cache.get_audiodb_album.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_album_detail_all_audiodb_fields_none(self):
        img_svc = _disabled_image_service()
        svc = _make_album_service(audiodb_service=img_svc)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_ALBUM_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.album_thumb_url is None
        assert result.album_back_url is None
        assert result.album_cdart_url is None
        assert result.album_spine_url is None
        assert result.album_3d_case_url is None
        assert result.album_3d_flat_url is None
        assert result.album_3d_face_url is None
        assert result.album_3d_thumb_url is None


class TestSettingsKillSwitchSearch:
    """8.10.d"""

    @pytest.mark.asyncio
    async def test_search_overlay_no_audiodb_urls(self):
        img_svc = _disabled_image_service()
        svc = _make_search_service(audiodb_service=img_svc)

        results = [
            SearchResult(type="artist", title="Coldplay", musicbrainz_id=TEST_ARTIST_MBID, score=100),
            SearchResult(type="album", title="Parachutes", musicbrainz_id=TEST_ALBUM_MBID, artist="Coldplay", score=90),
        ]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        assert results[0].fanart_url is None
        assert results[0].banner_url is None
        assert results[1].album_thumb_url is None


class TestNullGuardArtistDetail:

    @pytest.mark.asyncio
    async def test_null_service_all_audiodb_fields_none(self):
        svc = _make_artist_service(audiodb_service=None)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_ARTIST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.thumb_url is None
        assert result.fanart_url_2 is None
        assert result.fanart_url_3 is None
        assert result.fanart_url_4 is None
        assert result.wide_thumb_url is None
        assert result.logo_url is None
        assert result.clearart_url is None
        assert result.cutout_url is None


class TestNullGuardAlbumDetail:

    @pytest.mark.asyncio
    async def test_null_service_all_audiodb_fields_none(self):
        svc = _make_album_service(audiodb_service=None)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_ALBUM_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.album_thumb_url is None
        assert result.album_back_url is None
        assert result.album_cdart_url is None
        assert result.album_spine_url is None
        assert result.album_3d_case_url is None
        assert result.album_3d_flat_url is None
        assert result.album_3d_face_url is None
        assert result.album_3d_thumb_url is None


class TestNullGuardSearchOverlay:

    @pytest.mark.asyncio
    async def test_null_service_no_audiodb_urls(self):
        svc = _make_search_service(audiodb_service=None)

        results = [
            SearchResult(type="artist", title="Coldplay", musicbrainz_id=TEST_ARTIST_MBID, score=100),
            SearchResult(type="album", title="Parachutes", musicbrainz_id=TEST_ALBUM_MBID, artist="Coldplay", score=90),
        ]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        assert results[0].fanart_url is None
        assert results[0].banner_url is None
        assert results[1].album_thumb_url is None


class TestRepositoryDisabled:

    @pytest.mark.asyncio
    async def test_repository_disabled_returns_none_no_http(self):
        repo = _make_repo(enabled=False)

        result = await repo.get_artist_by_mbid(TEST_ARTIST_MBID)

        assert result is None
        repo._client.get.assert_not_called()

    @pytest.mark.asyncio
    async def test_repository_album_disabled_returns_none_no_http(self):
        repo = _make_repo(enabled=False)

        result = await repo.get_album_by_mbid(TEST_ALBUM_MBID)

        assert result is None
        repo._client.get.assert_not_called()


class TestCoverProviderDisabled:

    @pytest.mark.asyncio
    async def test_cover_provider_disabled_via_settings_skips_audiodb(self):
        """8.10.c: AudioDB cache not queried, fallback providers called normally."""
        http_get = AsyncMock()
        write_cache = AsyncMock()
        img_svc = _disabled_image_service()

        fetcher = AlbumCoverFetcher(
            http_get_fn=http_get,
            write_cache_fn=write_cache,
            audiodb_service=img_svc,
        )

        result = await fetcher._fetch_from_audiodb(
            TEST_ALBUM_MBID, Path("/tmp/fake_cover.jpg"),
        )

        assert result is None
        img_svc._disk_cache.get_audiodb_album.assert_not_awaited()
        http_get.assert_not_called()
        write_cache.assert_not_called()

    @pytest.mark.asyncio
    async def test_cover_provider_null_guard_skips_audiodb(self):
        """audiodb_service=None DI wiring defence."""
        http_get = AsyncMock()
        write_cache = AsyncMock()
        fetcher = AlbumCoverFetcher(
            http_get_fn=http_get,
            write_cache_fn=write_cache,
            audiodb_service=None,
        )

        result = await fetcher._fetch_from_audiodb(
            TEST_ALBUM_MBID, Path("/tmp/fake_cover.jpg"),
        )

        assert result is None
        http_get.assert_not_called()
        write_cache.assert_not_called()

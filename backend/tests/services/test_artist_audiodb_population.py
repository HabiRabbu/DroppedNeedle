from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.artist import ArtistInfo
from repositories.audiodb_models import AudioDBArtistImages
from services.artist_service import ArtistService


SAMPLE_IMAGES = AudioDBArtistImages(
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

TEST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"


def _make_artist_info(**overrides) -> ArtistInfo:
    defaults = dict(
        name="Coldplay",
        musicbrainz_id=TEST_MBID,
    )
    defaults.update(overrides)
    return ArtistInfo(**defaults)


def _make_service(
    audiodb_service: MagicMock | None = None,
) -> ArtistService:
    if audiodb_service is None:
        audiodb_service = MagicMock()
    return ArtistService(
        mb_repo=MagicMock(),
        library_repo=MagicMock(),
        wikidata_repo=MagicMock(),
        preferences_service=MagicMock(),
        memory_cache=MagicMock(),
        disk_cache=MagicMock(),
        audiodb_image_service=audiodb_service,
    )


class TestApplyAudioDBArtistImages:

    @pytest.mark.asyncio
    async def test_populates_all_fields(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.thumb_url == "https://cdn.example.com/thumb.jpg"
        assert result.fanart_url == "https://cdn.example.com/fanart1.jpg"
        assert result.fanart_url_2 == "https://cdn.example.com/fanart2.jpg"
        assert result.fanart_url_3 == "https://cdn.example.com/fanart3.jpg"
        assert result.fanart_url_4 == "https://cdn.example.com/fanart4.jpg"
        assert result.wide_thumb_url == "https://cdn.example.com/wide.jpg"
        assert result.banner_url == "https://cdn.example.com/banner.jpg"
        assert result.logo_url == "https://cdn.example.com/logo.png"
        assert result.clearart_url == "https://cdn.example.com/clearart.png"
        assert result.cutout_url == "https://cdn.example.com/cutout.png"

    @pytest.mark.asyncio
    async def test_library_fanart_not_overridden(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info(fanart_url="https://library.example.com/fanart.jpg")

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.fanart_url == "https://library.example.com/fanart.jpg"

    @pytest.mark.asyncio
    async def test_library_banner_not_overridden(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info(banner_url="https://library.example.com/banner.jpg")

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.banner_url == "https://library.example.com/banner.jpg"

    @pytest.mark.asyncio
    async def test_fills_missing_fanart(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info(fanart_url=None)

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.fanart_url == "https://cdn.example.com/fanart1.jpg"

    @pytest.mark.asyncio
    async def test_fills_missing_banner(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info(banner_url=None)

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.banner_url == "https://cdn.example.com/banner.jpg"

    @pytest.mark.asyncio
    async def test_no_service_returns_unchanged(self):
        svc = _make_service(audiodb_service=None)
        svc._audiodb_image_service = None
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.thumb_url is None
        assert result.fanart_url_2 is None

    @pytest.mark.asyncio
    async def test_cache_miss_returns_unchanged(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=None)
        svc = _make_service(audiodb)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=False,
        )

        assert result.thumb_url is None
        audiodb.get_cached_artist_images.assert_awaited_once_with(TEST_MBID)

    @pytest.mark.asyncio
    async def test_negative_cache_returns_unchanged(self):
        negative = AudioDBArtistImages.negative(lookup_source="mbid")
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=negative)
        svc = _make_service(audiodb)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.thumb_url is None

    @pytest.mark.asyncio
    async def test_fetch_mode_calls_fetch(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info()

        await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay",
            allow_fetch=True, is_monitored=True,
        )

        audiodb.fetch_and_cache_artist_images.assert_awaited_once_with(
            TEST_MBID, "Coldplay", is_monitored=True,
        )

    @pytest.mark.asyncio
    async def test_cache_only_mode_calls_get_cached(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        artist = _make_artist_info()

        await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=False,
        )

        audiodb.get_cached_artist_images.assert_awaited_once_with(TEST_MBID)
        audiodb.fetch_and_cache_artist_images.assert_not_called()

    @pytest.mark.asyncio
    async def test_exception_logged_not_raised(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_artist_images = AsyncMock(side_effect=RuntimeError("boom"))
        svc = _make_service(audiodb)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_MBID, "Coldplay", allow_fetch=True,
        )

        assert result.thumb_url is None
        assert result.name == "Coldplay"

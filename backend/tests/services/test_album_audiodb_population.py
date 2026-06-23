from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.album import AlbumInfo, AlbumBasicInfo
from repositories.audiodb_models import AudioDBAlbumImages
from services.album_service import AlbumService


SAMPLE_IMAGES = AudioDBAlbumImages(
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

TEST_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"


def _make_album_info(**overrides) -> AlbumInfo:
    defaults = dict(
        title="Parachutes",
        musicbrainz_id=TEST_MBID,
        artist_name="Coldplay",
        artist_id="cc197bad-dc9c-440d-a5b5-d52ba2e14234",
    )
    defaults.update(overrides)
    return AlbumInfo(**defaults)


def _make_service(
    audiodb_service: MagicMock | None = None,
) -> AlbumService:
    if audiodb_service is None:
        audiodb_service = MagicMock()
    return AlbumService(
        library_repo=MagicMock(),
        mb_repo=MagicMock(),
        library_db=MagicMock(),
        memory_cache=MagicMock(),
        disk_cache=MagicMock(),
        preferences_service=MagicMock(),
        audiodb_image_service=audiodb_service,
    )


class TestApplyAudioDBAlbumImages:

    @pytest.mark.asyncio
    async def test_populates_all_fields(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.album_thumb_url == "https://cdn.example.com/album_thumb.jpg"
        assert result.album_back_url == "https://cdn.example.com/album_back.jpg"
        assert result.album_cdart_url == "https://cdn.example.com/album_cdart.png"
        assert result.album_spine_url == "https://cdn.example.com/album_spine.jpg"
        assert result.album_3d_case_url == "https://cdn.example.com/3d_case.png"
        assert result.album_3d_flat_url == "https://cdn.example.com/3d_flat.png"
        assert result.album_3d_face_url == "https://cdn.example.com/3d_face.png"
        assert result.album_3d_thumb_url == "https://cdn.example.com/3d_thumb.png"

    @pytest.mark.asyncio
    async def test_cover_url_unchanged(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        album = _make_album_info(cover_url="https://coverart.example.com/cover.jpg")

        result = await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.cover_url == "https://coverart.example.com/cover.jpg"

    @pytest.mark.asyncio
    async def test_no_service_returns_unchanged(self):
        svc = _make_service(audiodb_service=None)
        svc._audiodb_image_service = None
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.album_thumb_url is None

    @pytest.mark.asyncio
    async def test_cache_miss_returns_unchanged(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=None)
        svc = _make_service(audiodb)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=False,
        )

        assert result.album_thumb_url is None
        audiodb.get_cached_album_images.assert_awaited_once_with(TEST_MBID)

    @pytest.mark.asyncio
    async def test_negative_cache_returns_unchanged(self):
        negative = AudioDBAlbumImages.negative(lookup_source="mbid")
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(return_value=negative)
        svc = _make_service(audiodb)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.album_thumb_url is None

    @pytest.mark.asyncio
    async def test_fetch_mode_calls_fetch(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        album = _make_album_info()

        await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes",
            allow_fetch=True, is_monitored=True,
        )

        audiodb.fetch_and_cache_album_images.assert_awaited_once_with(
            TEST_MBID, "Coldplay", "Parachutes", is_monitored=True,
        )

    @pytest.mark.asyncio
    async def test_cache_only_mode_calls_get_cached(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)
        album = _make_album_info()

        await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=False,
        )

        audiodb.get_cached_album_images.assert_awaited_once_with(TEST_MBID)

    @pytest.mark.asyncio
    async def test_exception_safe(self):
        audiodb = MagicMock()
        audiodb.fetch_and_cache_album_images = AsyncMock(side_effect=RuntimeError("boom"))
        svc = _make_service(audiodb)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_MBID, "Coldplay", "Parachutes", allow_fetch=True,
        )

        assert result.album_thumb_url is None
        assert result.title == "Parachutes"


class TestGetAudioDBAlbumThumb:

    @pytest.mark.asyncio
    async def test_returns_thumb_from_cache(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=SAMPLE_IMAGES)
        svc = _make_service(audiodb)

        result = await svc._get_audiodb_album_thumb(TEST_MBID)

        assert result == "https://cdn.example.com/album_thumb.jpg"

    @pytest.mark.asyncio
    async def test_returns_none_on_miss(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=None)
        svc = _make_service(audiodb)

        result = await svc._get_audiodb_album_thumb(TEST_MBID)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_negative(self):
        negative = AudioDBAlbumImages.negative(lookup_source="mbid")
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=negative)
        svc = _make_service(audiodb)

        result = await svc._get_audiodb_album_thumb(TEST_MBID)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_service(self):
        svc = _make_service(audiodb_service=None)
        svc._audiodb_image_service = None

        result = await svc._get_audiodb_album_thumb(TEST_MBID)

        assert result is None

    @pytest.mark.asyncio
    async def test_exception_safe(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(side_effect=RuntimeError("boom"))
        svc = _make_service(audiodb)

        result = await svc._get_audiodb_album_thumb(TEST_MBID)

        assert result is None

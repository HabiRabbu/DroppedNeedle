from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.search import SearchResult, SearchResponse
from repositories.audiodb_models import AudioDBArtistImages, AudioDBAlbumImages
from services.search_service import SearchService


TEST_ARTIST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
TEST_ALBUM_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"

ARTIST_IMAGES = AudioDBArtistImages(
    thumb_url="https://cdn.example.com/artist_thumb.jpg",
    fanart_url="https://cdn.example.com/fanart1.jpg",
    banner_url="https://cdn.example.com/banner.jpg",
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)

ALBUM_IMAGES = AudioDBAlbumImages(
    album_thumb_url="https://cdn.example.com/album_thumb.jpg",
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)

NEGATIVE_ARTIST = AudioDBArtistImages.negative(lookup_source="mbid")
NEGATIVE_ALBUM = AudioDBAlbumImages.negative(lookup_source="mbid")


def _artist_result(**overrides) -> SearchResult:
    defaults = dict(type="artist", title="Coldplay", musicbrainz_id=TEST_ARTIST_MBID, score=100)
    defaults.update(overrides)
    return SearchResult(**defaults)


def _album_result(**overrides) -> SearchResult:
    defaults = dict(type="album", title="Parachutes", musicbrainz_id=TEST_ALBUM_MBID, artist="Coldplay", score=90)
    defaults.update(overrides)
    return SearchResult(**defaults)


def _search_service(audiodb=None) -> SearchService:
    mb_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_mbids = AsyncMock(return_value=set())
    coverart_repo = MagicMock()
    prefs = MagicMock()
    prefs.get_preferences.return_value = MagicMock(secondary_types=[])
    return SearchService(mb_repo, library_repo, coverart_repo, prefs, audiodb)


class TestSearchAudioDBOverlayArtist:
    @pytest.mark.asyncio
    async def test_artist_gets_cached_thumb_fanart_banner(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        svc = _search_service(audiodb)

        results = [_artist_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url == "https://cdn.example.com/artist_thumb.jpg"
        assert results[0].fanart_url == "https://cdn.example.com/fanart1.jpg"
        assert results[0].banner_url == "https://cdn.example.com/banner.jpg"
        audiodb.get_cached_artist_images.assert_awaited_once_with(TEST_ARTIST_MBID)

    @pytest.mark.asyncio
    async def test_artist_cache_miss_leaves_none(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=None)
        svc = _search_service(audiodb)

        results = [_artist_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        assert results[0].fanart_url is None
        assert results[0].banner_url is None

    @pytest.mark.asyncio
    async def test_artist_negative_cache_leaves_none(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=NEGATIVE_ARTIST)
        svc = _search_service(audiodb)

        results = [_artist_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        assert results[0].fanart_url is None
        assert results[0].banner_url is None

    @pytest.mark.asyncio
    async def test_artist_existing_fields_not_overwritten(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        svc = _search_service(audiodb)

        results = [_artist_result(thumb_url="https://existing.com/thumb.jpg")]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url == "https://existing.com/thumb.jpg"
        assert results[0].fanart_url == "https://cdn.example.com/fanart1.jpg"


class TestSearchAudioDBOverlayAlbum:
    @pytest.mark.asyncio
    async def test_album_gets_cached_thumb(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _search_service(audiodb)

        results = [_album_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].album_thumb_url == "https://cdn.example.com/album_thumb.jpg"
        audiodb.get_cached_album_images.assert_awaited_once_with(TEST_ALBUM_MBID)

    @pytest.mark.asyncio
    async def test_album_cache_miss_leaves_none(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=None)
        svc = _search_service(audiodb)

        results = [_album_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].album_thumb_url is None

    @pytest.mark.asyncio
    async def test_album_negative_cache_leaves_none(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=NEGATIVE_ALBUM)
        svc = _search_service(audiodb)

        results = [_album_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].album_thumb_url is None

    @pytest.mark.asyncio
    async def test_album_existing_thumb_not_overwritten(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _search_service(audiodb)

        results = [_album_result(album_thumb_url="https://existing.com/album.jpg")]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].album_thumb_url == "https://existing.com/album.jpg"


class TestSearchAudioDBOverlayMixed:
    @pytest.mark.asyncio
    async def test_mixed_results_overlay(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        audiodb.get_cached_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _search_service(audiodb)

        results = [_artist_result(), _album_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url == "https://cdn.example.com/artist_thumb.jpg"
        assert results[1].album_thumb_url == "https://cdn.example.com/album_thumb.jpg"

    @pytest.mark.asyncio
    async def test_empty_results_no_error(self):
        audiodb = MagicMock()
        svc = _search_service(audiodb)

        results: list[SearchResult] = []
        await svc._apply_audiodb_search_overlay(results)

        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_no_audiodb_service_is_noop(self):
        svc = _search_service(audiodb=None)

        results = [_artist_result(), _album_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        assert results[1].album_thumb_url is None

    @pytest.mark.asyncio
    async def test_exception_in_one_item_does_not_break_others(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(side_effect=RuntimeError("db error"))
        audiodb.get_cached_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _search_service(audiodb)

        results = [_artist_result(), _album_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        assert results[1].album_thumb_url == "https://cdn.example.com/album_thumb.jpg"

    @pytest.mark.asyncio
    async def test_empty_mbid_skipped(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        svc = _search_service(audiodb)

        results = [_artist_result(musicbrainz_id="")]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url is None
        audiodb.get_cached_artist_images.assert_not_awaited()


class TestSearchMethodIntegration:
    @pytest.mark.asyncio
    async def test_search_calls_overlay(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        audiodb.get_cached_album_images = AsyncMock(return_value=ALBUM_IMAGES)
        svc = _search_service(audiodb)

        artist = _artist_result()
        album = _album_result()
        svc._mb_repo.search_grouped = AsyncMock(return_value={"artists": [artist], "albums": [album]})

        result = await svc.search("coldplay")

        assert result.artists[0].thumb_url == "https://cdn.example.com/artist_thumb.jpg"
        assert result.albums[0].album_thumb_url == "https://cdn.example.com/album_thumb.jpg"

    @pytest.mark.asyncio
    async def test_search_bucket_calls_overlay(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=ARTIST_IMAGES)
        svc = _search_service(audiodb)

        artist = _artist_result()
        svc._mb_repo.search_artists = AsyncMock(return_value=[artist])

        result, _top = await svc.search_bucket("artists", "coldplay")

        assert result[0].thumb_url == "https://cdn.example.com/artist_thumb.jpg"

"""Integration tests verifying the URL-only path for non-library items.

Search/list endpoints must carry AudioDB CDN URLs in responses WITHOUT
triggering byte downloads.  These tests confirm that:
- Search overlay populates URLs from cache, never fetches.
- Artist list (allow_fetch=False) uses cache only.
- Album list (allow_fetch=False) uses cache only.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.album import AlbumInfo
from api.v1.schemas.artist import ArtistInfo
from api.v1.schemas.search import SearchResult
from repositories.audiodb_models import AudioDBArtistImages, AudioDBAlbumImages
from services.album_service import AlbumService
from services.artist_service import ArtistService
from services.search_service import SearchService


TEST_ARTIST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"
TEST_ALBUM_MBID = "1dc4c347-a1db-32aa-b14f-bc9cc507b843"

CACHED_ARTIST_IMAGES = AudioDBArtistImages(
    thumb_url="https://r2.theaudiodb.com/artist.jpg",
    fanart_url="https://r2.theaudiodb.com/fanart.jpg",
    banner_url="https://r2.theaudiodb.com/banner.jpg",
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)

CACHED_ALBUM_IMAGES = AudioDBAlbumImages(
    album_thumb_url="https://r2.theaudiodb.com/album_thumb.jpg",
    lookup_source="mbid",
    is_negative=False,
    cached_at=1000.0,
)



def _artist_result(**overrides) -> SearchResult:
    defaults = dict(type="artist", title="Coldplay", musicbrainz_id=TEST_ARTIST_MBID, score=100)
    defaults.update(overrides)
    return SearchResult(**defaults)


def _search_service(audiodb: MagicMock | None = None) -> SearchService:
    mb_repo = MagicMock()
    library_repo = MagicMock()
    library_repo.get_library_mbids = AsyncMock(return_value=set())
    coverart_repo = MagicMock()
    prefs = MagicMock()
    prefs.get_preferences.return_value = MagicMock(secondary_types=[])
    return SearchService(mb_repo, library_repo, coverart_repo, prefs, audiodb)


def _make_artist_info(**overrides) -> ArtistInfo:
    defaults = dict(name="Coldplay", musicbrainz_id=TEST_ARTIST_MBID)
    defaults.update(overrides)
    return ArtistInfo(**defaults)


def _make_artist_service(audiodb_service: MagicMock | None = None) -> ArtistService:
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


def _make_album_info(**overrides) -> AlbumInfo:
    defaults = dict(
        title="Parachutes",
        musicbrainz_id=TEST_ALBUM_MBID,
        artist_name="Coldplay",
        artist_id=TEST_ARTIST_MBID,
    )
    defaults.update(overrides)
    return AlbumInfo(**defaults)


def _make_album_service(audiodb_service: MagicMock | None = None) -> AlbumService:
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



class TestSearchOverlayURLsWithoutByteDownload:
    """Search overlay must populate AudioDB CDN URLs from cache only."""

    @pytest.mark.asyncio
    async def test_search_overlay_populates_urls_without_byte_download(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=CACHED_ARTIST_IMAGES)
        svc = _search_service(audiodb)

        results = [_artist_result()]
        await svc._apply_audiodb_search_overlay(results)

        assert results[0].thumb_url == "https://r2.theaudiodb.com/artist.jpg"
        assert results[0].fanart_url == "https://r2.theaudiodb.com/fanart.jpg"
        assert results[0].banner_url == "https://r2.theaudiodb.com/banner.jpg"

        audiodb.fetch_and_cache_artist_images.assert_not_called()

        audiodb.get_cached_artist_images.assert_awaited_once_with(TEST_ARTIST_MBID)



class TestArtistListCacheOnlyNoAPICall:
    """Artist service with allow_fetch=False must use cache, never API."""

    @pytest.mark.asyncio
    async def test_artist_list_cache_only_no_api_call(self):
        audiodb = MagicMock()
        audiodb.get_cached_artist_images = AsyncMock(return_value=CACHED_ARTIST_IMAGES)
        svc = _make_artist_service(audiodb)
        artist = _make_artist_info()

        result = await svc._apply_audiodb_artist_images(
            artist, TEST_ARTIST_MBID, "Coldplay", allow_fetch=False,
        )

        assert result.thumb_url == "https://r2.theaudiodb.com/artist.jpg"
        assert result.fanart_url == "https://r2.theaudiodb.com/fanart.jpg"
        assert result.banner_url == "https://r2.theaudiodb.com/banner.jpg"

        audiodb.fetch_and_cache_artist_images.assert_not_called()

        audiodb.get_cached_artist_images.assert_awaited_once_with(TEST_ARTIST_MBID)



class TestAlbumListCacheOnlyNoAPICall:
    """Album service with allow_fetch=False must use cache, never API."""

    @pytest.mark.asyncio
    async def test_album_list_cache_only_no_api_call(self):
        audiodb = MagicMock()
        audiodb.get_cached_album_images = AsyncMock(return_value=CACHED_ALBUM_IMAGES)
        svc = _make_album_service(audiodb)
        album = _make_album_info()

        result = await svc._apply_audiodb_album_images(
            album, TEST_ALBUM_MBID, "Coldplay", "Parachutes", allow_fetch=False,
        )

        assert result.album_thumb_url == "https://r2.theaudiodb.com/album_thumb.jpg"

        audiodb.fetch_and_cache_album_images.assert_not_called()

        audiodb.get_cached_album_images.assert_awaited_once_with(TEST_ALBUM_MBID)

"""Integration tests: provider chain falls through correctly when AudioDB has no data."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from api.v1.schemas.artist import ArtistInfo
from repositories.audiodb_models import AudioDBAlbumImages, AudioDBArtistImages
from repositories.coverart_album import AlbumCoverFetcher
from repositories.coverart_artist import ArtistImageFetcher
from services.artist_service import ArtistService


TEST_MBID = "cc197bad-dc9c-440d-a5b5-d52ba2e14234"


def _response(
    status_code: int = 200,
    content_type: str = "image/jpeg",
    content: bytes = b"img",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.content = content
    return resp


def _make_artist_info(**overrides) -> ArtistInfo:
    defaults = dict(name="Coldplay", musicbrainz_id=TEST_MBID)
    defaults.update(overrides)
    return ArtistInfo(**defaults)


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


@pytest.mark.asyncio
async def test_album_chain_audiodb_none_falls_to_coverart_archive():
    http_get = AsyncMock(return_value=_response(content=b"caa-cover"))
    audiodb_service = MagicMock()
    audiodb_service.get_cached_album_images = AsyncMock(return_value=None)
    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=AsyncMock(),
        audiodb_service=audiodb_service,
    )
    fetcher._fetch_release_group_local_sources = AsyncMock(return_value=None)
    fetcher._get_cover_from_best_release = AsyncMock(return_value=None)

    result = await fetcher.fetch_release_group_cover(
        "release-group-id", None, Path("/tmp/album.bin"),
    )

    assert result is not None
    assert result == (b"caa-cover", "image/jpeg", "cover-art-archive")
    audiodb_service.get_cached_album_images.assert_awaited_once_with("release-group-id")
    http_get.assert_awaited_once()


@pytest.mark.asyncio
async def test_album_chain_audiodb_negative_falls_to_coverart_archive():
    http_get = AsyncMock(return_value=_response(content=b"caa-cover"))
    audiodb_service = MagicMock()
    audiodb_service.get_cached_album_images = AsyncMock(
        return_value=AudioDBAlbumImages(is_negative=True),
    )
    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=AsyncMock(),
        audiodb_service=audiodb_service,
    )
    fetcher._fetch_release_group_local_sources = AsyncMock(return_value=None)
    fetcher._get_cover_from_best_release = AsyncMock(return_value=None)

    result = await fetcher.fetch_release_group_cover(
        "release-group-id", None, Path("/tmp/album.bin"),
    )

    assert result is not None
    assert result == (b"caa-cover", "image/jpeg", "cover-art-archive")
    audiodb_service.get_cached_album_images.assert_awaited_once_with("release-group-id")


@pytest.mark.asyncio
async def test_artist_chain_audiodb_none_falls_to_wikidata():
    audiodb_service = MagicMock()
    audiodb_service.get_cached_artist_images = AsyncMock(return_value=None)
    fetcher = ArtistImageFetcher(
        http_get_fn=AsyncMock(),
        write_cache_fn=AsyncMock(),
        cache=MagicMock(),
        audiodb_service=audiodb_service,
    )
    fetcher._fetch_local_sources = AsyncMock(return_value=(None, False))
    fetcher._fetch_from_wikidata = AsyncMock(
        return_value=(b"wiki-img", "image/jpeg", "wikidata"),
    )

    result = await fetcher.fetch_artist_image(
        "artist-id", 300, Path("/tmp/artist.bin"),
    )

    assert result is not None
    assert result[2] == "wikidata"
    assert result[0] == b"wiki-img"
    fetcher._fetch_from_wikidata.assert_awaited_once()


@pytest.mark.asyncio
async def test_full_chain_audiodb_and_coverart_both_empty():
    http_get = AsyncMock(return_value=_response(status_code=404))
    audiodb_service = MagicMock()
    audiodb_service.get_cached_album_images = AsyncMock(return_value=None)
    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=AsyncMock(),
        audiodb_service=audiodb_service,
    )
    fetcher._fetch_release_group_local_sources = AsyncMock(return_value=None)
    fetcher._get_cover_from_best_release = AsyncMock(return_value=None)

    result = await fetcher.fetch_release_group_cover(
        "release-group-id", None, Path("/tmp/album.bin"),
    )

    assert result is None
    audiodb_service.get_cached_album_images.assert_awaited_once()
    fetcher._get_cover_from_best_release.assert_awaited_once()


@pytest.mark.asyncio
async def test_artist_detail_audiodb_no_data_fields_none():
    audiodb_service = MagicMock()
    audiodb_service.fetch_and_cache_artist_images = AsyncMock(return_value=None)
    svc = _make_artist_service(audiodb_service)
    artist = _make_artist_info(
        fanart_url="https://library.example.com/fanart.jpg",
        banner_url="https://library.example.com/banner.jpg",
    )

    result = await svc._apply_audiodb_artist_images(
        artist, TEST_MBID, "Coldplay", allow_fetch=True,
    )

    assert result.thumb_url is None
    assert result.fanart_url_2 is None
    assert result.fanart_url_3 is None
    assert result.fanart_url_4 is None
    assert result.wide_thumb_url is None
    assert result.logo_url is None
    assert result.clearart_url is None
    assert result.cutout_url is None
    assert result.fanart_url == "https://library.example.com/fanart.jpg"
    assert result.banner_url == "https://library.example.com/banner.jpg"

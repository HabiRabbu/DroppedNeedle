import asyncio
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from repositories.audiodb_models import AudioDBAlbumImages, AudioDBArtistImages
from repositories.coverart_album import AlbumCoverFetcher
from repositories.coverart_artist import ArtistImageFetcher

AUDIODB_CDN_URL = "https://r2.theaudiodb.com/test.jpg"
AUDIODB_ARTIST_CDN_URL = "https://r2.theaudiodb.com/artist.jpg"
CAA_URL_PREFIX = "https://coverartarchive.org"


def _response(
    status_code: int = 200,
    content_type: str = "image/jpeg",
    content: bytes = b"img",
) -> MagicMock:
    response = MagicMock()
    response.status_code = status_code
    response.headers = {"content-type": content_type}
    response.content = content
    return response


@pytest.mark.asyncio
async def test_album_byte_path_cache_hit_downloads_and_caches():
    """8.5.a - Full chain: AudioDB cache hit → CDN download → disk write.
    CoverArtArchive is NOT called (short-circuited)."""
    audiodb_response = _response(content=b"fake-jpeg-bytes")
    http_get = AsyncMock(return_value=audiodb_response)
    write_cache = AsyncMock()
    audiodb_service = MagicMock()
    audiodb_service.get_cached_album_images = AsyncMock(
        return_value=AudioDBAlbumImages(
            album_thumb_url=AUDIODB_CDN_URL,
            is_negative=False,
            cached_at=time.time(),
        ),
    )
    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=write_cache,
        audiodb_service=audiodb_service,
    )

    result = await fetcher.fetch_release_group_cover(
        "release-group-id", "500", Path("/tmp/album.bin"),
    )

    assert result == (b"fake-jpeg-bytes", "image/jpeg", "audiodb")
    http_get.assert_awaited_once()
    assert http_get.call_args[0][0] == AUDIODB_CDN_URL
    await asyncio.sleep(0)
    assert write_cache.await_count == 1
    write_meta = write_cache.call_args[0][3]
    assert write_meta == {"source": "audiodb"}


@pytest.mark.asyncio
async def test_artist_byte_path_cache_hit_downloads_and_caches():
    """8.5.b - Full chain: AudioDB cache hit → CDN download → disk write.
    Wikidata is NOT called (short-circuited)."""
    http_get = AsyncMock(
        return_value=_response(content=b"fake-artist-bytes"),
    )
    write_cache = AsyncMock()
    audiodb_service = MagicMock()
    audiodb_service.get_cached_artist_images = AsyncMock(
        return_value=AudioDBArtistImages(
            thumb_url=AUDIODB_ARTIST_CDN_URL,
            is_negative=False,
            cached_at=time.time(),
        ),
    )
    fetcher = ArtistImageFetcher(
        http_get_fn=http_get,
        write_cache_fn=write_cache,
        cache=MagicMock(),
        audiodb_service=audiodb_service,
    )

    result = await fetcher.fetch_artist_image(
        "artist-id-00", 500, Path("/tmp/artist.bin"),
    )

    assert result == (b"fake-artist-bytes", "image/jpeg", "audiodb")
    http_get.assert_awaited_once()
    assert http_get.call_args[0][0] == AUDIODB_ARTIST_CDN_URL
    await asyncio.sleep(0)
    assert write_cache.await_count == 1
    write_meta = write_cache.call_args[0][3]
    assert write_meta == {"source": "audiodb"}


@pytest.mark.asyncio
async def test_album_byte_path_cdn_404_falls_through_to_caa():
    """8.5.c - CDN returns 404 → AudioDB falls through → CoverArtArchive is called."""
    cdn_404 = _response(status_code=404)
    caa_ok = _response(content=b"caa-bytes", content_type="image/png")

    async def _route_http_get(url, *args, **kwargs):
        if "theaudiodb.com" in url:
            return cdn_404
        return caa_ok

    http_get = AsyncMock(side_effect=_route_http_get)
    write_cache = AsyncMock()
    audiodb_service = MagicMock()
    audiodb_service.get_cached_album_images = AsyncMock(
        return_value=AudioDBAlbumImages(
            album_thumb_url=AUDIODB_CDN_URL,
            is_negative=False,
            cached_at=time.time(),
        ),
    )
    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=write_cache,
        audiodb_service=audiodb_service,
    )

    result = await fetcher.fetch_release_group_cover(
        "release-group-id", "500", Path("/tmp/album.bin"),
    )

    assert result == (b"caa-bytes", "image/png", "cover-art-archive")
    urls_called = [c[0][0] for c in http_get.call_args_list]
    assert AUDIODB_CDN_URL in urls_called
    assert any(CAA_URL_PREFIX in u for u in urls_called)
    await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_album_byte_path_cdn_invalid_content_type_falls_through():
    """8.5.d - CDN returns text/html → AudioDB falls through → CoverArtArchive called."""
    cdn_html = _response(status_code=200, content_type="text/html")
    caa_ok = _response(content=b"caa-bytes", content_type="image/jpeg")

    async def _route_http_get(url, *args, **kwargs):
        if "theaudiodb.com" in url:
            return cdn_html
        return caa_ok

    http_get = AsyncMock(side_effect=_route_http_get)
    write_cache = AsyncMock()
    audiodb_service = MagicMock()
    audiodb_service.get_cached_album_images = AsyncMock(
        return_value=AudioDBAlbumImages(
            album_thumb_url=AUDIODB_CDN_URL,
            is_negative=False,
            cached_at=time.time(),
        ),
    )
    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=write_cache,
        audiodb_service=audiodb_service,
    )

    result = await fetcher.fetch_release_group_cover(
        "release-group-id", "500", Path("/tmp/album.bin"),
    )

    assert result == (b"caa-bytes", "image/jpeg", "cover-art-archive")
    await asyncio.sleep(0)

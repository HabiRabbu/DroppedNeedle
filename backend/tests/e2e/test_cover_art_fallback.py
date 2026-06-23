"""End-to-end cover-art fallback chain, validated after Lidarr removal.

The album cover chain (``AlbumCoverFetcher.fetch_release_group_cover``) is, in order:
AudioDB -> local sources (library / Jellyfin) -> Cover Art Archive -> best release.
With Lidarr gone the library source is ``None``; these tests prove the chain still
resolves a cover (first success wins) for an album that has no embedded art, with no
network calls (the HTTP getter and AudioDB service are mocked).

Note: Wikidata is part of the *artist* image chain, not the album cover chain; the
album chain's CDN fallback is the Cover Art Archive.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from repositories.audiodb_models import AudioDBAlbumImages
from repositories.coverart_album import AlbumCoverFetcher

_RG = "b1392450-e666-3926-a536-22c65f834433"


def _image_response(content: bytes = b"PNGDATA", content_type: str = "image/jpeg"):
    response = MagicMock()
    response.status_code = 200
    response.headers = {"content-type": content_type}
    response.content = content
    return response


def _miss_response():
    response = MagicMock()
    response.status_code = 404
    response.headers = {}
    response.content = b""
    return response


@pytest.mark.asyncio
async def test_falls_back_to_cover_art_archive_without_lidarr(tmp_path: Path):
    """No AudioDB image, no local library (Lidarr removed) -> CAA resolves the cover."""
    http_get = AsyncMock(return_value=_image_response(b"caa-bytes"))
    audiodb = MagicMock()
    audiodb.fetch_and_cache_album_images = AsyncMock(return_value=None)  # AudioDB miss

    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=AsyncMock(),
        library_repo=None,  # Lidarr removed
        jellyfin_repo=None,
        audiodb_service=audiodb,
    )

    result = await fetcher.fetch_release_group_cover(_RG, "500", tmp_path / "cover.bin")

    assert result is not None
    content, _content_type, source = result
    assert content == b"caa-bytes"
    assert source == "cover-art-archive"
    # AudioDB was consulted first, then the CAA HTTP endpoint was hit.
    audiodb.fetch_and_cache_album_images.assert_awaited_once_with(_RG)
    caa_url = http_get.call_args_list[0].args[0]
    assert caa_url.startswith("https://coverartarchive.org/release-group/")


@pytest.mark.asyncio
async def test_audiodb_wins_and_short_circuits_the_chain(tmp_path: Path):
    """When AudioDB has the art, the chain returns it and never reaches the CAA."""
    audiodb = MagicMock()
    audiodb.fetch_and_cache_album_images = AsyncMock(
        return_value=AudioDBAlbumImages(album_thumb_url="https://r2.theaudiodb.com/album.jpg")
    )
    http_get = AsyncMock(return_value=_image_response(b"audiodb-bytes"))

    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=AsyncMock(),
        library_repo=None,
        jellyfin_repo=None,
        audiodb_service=audiodb,
    )

    result = await fetcher.fetch_release_group_cover(_RG, "500", tmp_path / "cover.bin")

    assert result is not None
    content, _content_type, source = result
    assert content == b"audiodb-bytes"
    assert source == "audiodb"
    # Only the AudioDB thumbnail was downloaded - the CAA endpoint was never called.
    assert http_get.await_count == 1
    assert http_get.call_args_list[0].args[0] == "https://r2.theaudiodb.com/album.jpg"


@pytest.mark.asyncio
async def test_no_source_resolves_returns_none(tmp_path: Path):
    """Every source missing -> the chain returns None rather than raising."""
    http_get = AsyncMock(return_value=_miss_response())
    audiodb = MagicMock()
    audiodb.fetch_and_cache_album_images = AsyncMock(return_value=None)

    fetcher = AlbumCoverFetcher(
        http_get_fn=http_get,
        write_cache_fn=AsyncMock(),
        library_repo=None,
        jellyfin_repo=None,
        audiodb_service=audiodb,
    )

    result = await fetcher.fetch_release_group_cover(_RG, "500", tmp_path / "cover.bin")
    assert result is None

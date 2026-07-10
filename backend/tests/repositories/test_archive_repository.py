"""ArchiveRepository: the licence filter, the dark-item degradation, and the
response shapes recorded in repositories/ARCHIVE_API_NOTES.md."""

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from core.exceptions import RateLimitedError
from repositories.archive_repository import (
    ArchiveError,
    ArchiveRepository,
    is_open_licence,
)

CC = "http://creativecommons.org/licenses/by-nc-sa/3.0/"
PD = "https://creativecommons.org/publicdomain/zero/1.0/"


def _response(status_code: int, payload: dict | None = None) -> httpx.Response:
    return httpx.Response(
        status_code=status_code,
        content=json.dumps(payload if payload is not None else {}).encode(),
        request=httpx.Request("GET", "https://archive.org/x"),
    )


def _repo(response: httpx.Response) -> tuple[ArchiveRepository, AsyncMock]:
    client = AsyncMock()
    client.get = AsyncMock(return_value=response)
    return ArchiveRepository(client), client


@pytest.fixture(autouse=True)
def _reset_breaker():
    ArchiveRepository.reset_circuit_breaker()
    yield
    ArchiveRepository.reset_circuit_breaker()


# -- the licence filter (D24: this client only surfaces licensed items) --


@pytest.mark.parametrize(
    "value,expected",
    [
        (CC, True),
        (PD, True),
        ("https://creativecommons.org/licenses/by/4.0/", True),
        ("", False),
        (None, False),
        ("http://example.com/all-rights-reserved", False),
        ("https://evil.example/creativecommons.org/licenses/by/4.0/", False),
    ],
)
def test_is_open_licence(value, expected):
    assert is_open_licence(value) is expected


@pytest.mark.asyncio
async def test_search_drops_items_without_an_open_licence():
    repo, _ = _repo(
        _response(
            200,
            {
                "response": {
                    "docs": [
                        {"identifier": "good", "title": "Good", "licenseurl": CC},
                        {"identifier": "unlicensed", "title": "Bad"},
                        {"identifier": "closed", "title": "Bad", "licenseurl": "http://x/arr"},
                    ]
                }
            },
        )
    )

    items = await repo.search_audio("Brad Sucks", "Guess Who's a Mess")

    assert [i.identifier for i in items] == ["good"]
    assert items[0].licence_url == CC


@pytest.mark.asyncio
async def test_search_normalises_a_list_valued_creator():
    """Live shape: an item can name the same artist twice."""
    repo, _ = _repo(
        _response(
            200,
            {
                "response": {
                    "docs": [
                        {
                            "identifier": "x",
                            "title": "T",
                            "creator": ["Brad Sucks", "Brad Sucks"],
                            "licenseurl": CC,
                            "year": "2012",
                        }
                    ]
                }
            },
        )
    )

    items = await repo.search_audio("Brad Sucks", "T")
    assert items[0].creator == "Brad Sucks, Brad Sucks"
    assert items[0].year == 2012


@pytest.mark.asyncio
async def test_search_without_artist_or_title_makes_no_call():
    repo, client = _repo(_response(200, {}))
    assert await repo.search_audio("", "") == []
    client.get.assert_not_awaited()


# -- item files --


@pytest.mark.asyncio
async def test_get_item_files_returns_audio_with_track_numbers():
    repo, _ = _repo(
        _response(
            200,
            {
                "metadata": {"licenseurl": CC},
                "files": [
                    {"name": "01.mp3", "format": "VBR MP3", "size": "500", "track": "1", "title": "One"},
                    {"name": "01.flac", "format": "FLAC", "size": "5000", "track": "1"},
                    {"name": "cover.jpg", "format": "JPEG", "size": "10"},
                ],
            },
        )
    )

    licence, files = await repo.get_item_files("x")

    assert licence == CC
    assert sorted(f.name for f in files) == ["01.flac", "01.mp3"]
    mp3 = next(f for f in files if f.name.endswith(".mp3"))
    assert mp3.size_bytes == 500 and mp3.track == 1 and mp3.title == "One"


@pytest.mark.asyncio
async def test_dark_item_returns_no_files_and_does_not_raise():
    """A removed item answers {} rather than 404 (ARCHIVE_API_NOTES)."""
    repo, _ = _repo(_response(200, {}))
    assert await repo.get_item_files("gone") == ("", [])


@pytest.mark.asyncio
async def test_item_without_open_licence_yields_no_files():
    repo, _ = _repo(
        _response(200, {"metadata": {"licenseurl": ""}, "files": [{"name": "a.mp3", "format": "MP3"}]})
    )
    assert await repo.get_item_files("a-new-low-in-hifi") == ("", [])


# -- transport --


@pytest.mark.asyncio
async def test_rate_limit_raises_rate_limited_error():
    repo, _ = _repo(_response(429))
    with pytest.raises(RateLimitedError):
        await repo.search_audio("A", "B")


@pytest.mark.asyncio
async def test_server_error_raises_archive_error():
    repo, _ = _repo(_response(500))
    with pytest.raises(ArchiveError):
        await repo.search_audio("A", "B")


@pytest.mark.asyncio
async def test_invalid_json_raises_archive_error():
    client = AsyncMock()
    client.get = AsyncMock(
        return_value=httpx.Response(
            200, content=b"<html>", request=httpx.Request("GET", "https://archive.org/x")
        )
    )
    with pytest.raises(ArchiveError):
        await ArchiveRepository(client).search_audio("A", "B")


def test_extension_for_maps_the_live_format_strings():
    repo = ArchiveRepository(AsyncMock())
    assert repo.extension_for("VBR MP3") == "mp3"
    assert repo.extension_for("FLAC") == "flac"
    assert repo.extension_for("24bit FLAC") == "flac"
    assert repo.extension_for("JPEG") == ""

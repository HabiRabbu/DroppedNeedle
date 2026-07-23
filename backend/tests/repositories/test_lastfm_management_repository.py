import inspect
import json
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from core.exceptions import ExternalServiceError, RateLimitedError
from infrastructure.cache.cache_keys import (
    LFM_PREFIX,
    lastfm_management_album_genres_key,
    lastfm_management_artist_genres_key,
    lastfm_prefixes,
)
from infrastructure.cache.memory_cache import InMemoryCache
from repositories.lastfm_repository import LastFmRepository
from repositories.protocols.lastfm_management import LastFmGenreRepositoryProtocol

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "lastfm"
    / "management_top_tags.json"
)


@pytest.mark.asyncio
async def test_weighted_album_and_artist_tags_use_verified_shapes_and_cache() -> None:
    payloads = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        method = request.url.params["method"]
        key = "album" if method == "album.getTopTags" else "artist"
        return httpx.Response(200, json=payloads[key], request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = InMemoryCache()
        repository = LastFmRepository(client, cache, api_key="configured")
        album = await repository.get_album_top_genres(
            artist_name="Radiohead", album_title="The Bends"
        )
        cached_album = await repository.get_album_top_genres(
            artist_name="Radiohead", album_title="The Bends"
        )
        artist = await repository.get_artist_top_genres(artist_name="Radiohead")

    assert len(requests) == 2
    assert requests[0].url.params["autocorrect"] == "0"
    assert requests[0].url.params["artist"] == "Radiohead"
    assert requests[0].url.params["album"] == "The Bends"
    assert requests[1].url.params["method"] == "artist.getTopTags"
    assert [value.display_name for value in album] == ["alternative rock", "rock"]
    assert [value.weight for value in album] == [100, 82]
    assert album[0].provider_entity == "album"
    assert artist[0].provider_entity == "artist"
    assert cached_album == album
    assert (
        await cache.get(lastfm_management_album_genres_key("Radiohead", "The Bends"))
        == album
    )
    assert await cache.get(lastfm_management_artist_genres_key("Radiohead")) == artist
    assert LFM_PREFIX in lastfm_prefixes()


@pytest.mark.asyncio
async def test_invalid_weighted_tag_shape_raises_typed_provider_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"toptags": {"tag": [{"name": "rock", "count": "many"}]}},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LastFmRepository(client, InMemoryCache(), api_key="configured")
        with pytest.raises(ExternalServiceError, match="invalid weighted tag"):
            await repository.get_artist_top_genres(artist_name="Radiohead")


@pytest.mark.asyncio
async def test_missing_album_tags_do_not_hide_available_artist_tags() -> None:
    payloads = json.loads(_FIXTURE.read_text(encoding="utf-8"))

    def handler(request: httpx.Request) -> httpx.Response:
        payload = (
            {"error": 6, "message": "Album not found"}
            if request.url.params["method"] == "album.getTopTags"
            else payloads["artist"]
        )
        return httpx.Response(200, json=payload, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LastFmRepository(client, InMemoryCache(), api_key="configured")
        album = await repository.get_album_top_genres(
            artist_name="Radiohead", album_title="Missing"
        )
        artist = await repository.get_artist_top_genres(artist_name="Radiohead")

    assert album == ()
    assert artist
    assert all(value.provider_entity == "artist" for value in artist)


@pytest.mark.asyncio
async def test_error_29_is_a_typed_rate_limit_with_bounded_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    retry_sleep = AsyncMock()
    monkeypatch.setattr("infrastructure.resilience.retry.asyncio.sleep", retry_sleep)
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(
            200,
            json={"error": 29, "message": "Rate limit exceeded"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LastFmRepository(client, InMemoryCache(), api_key="configured")
        with pytest.raises(RateLimitedError) as raised:
            await repository.get_artist_top_genres(artist_name="Radiohead")

    assert raised.value.retry_after_seconds == 1.0
    assert requests == 3
    assert [call.args[0] for call in retry_sleep.await_args_list] == [1.0, 1.0]


def test_management_methods_conform_to_narrow_protocol() -> None:
    assert inspect.signature(LastFmGenreRepositoryProtocol.get_album_top_genres) == (
        inspect.signature(LastFmRepository.get_album_top_genres)
    )
    assert inspect.signature(LastFmGenreRepositoryProtocol.get_artist_top_genres) == (
        inspect.signature(LastFmRepository.get_artist_top_genres)
    )

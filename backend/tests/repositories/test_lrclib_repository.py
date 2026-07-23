import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from core.exceptions import LrclibApiError, RateLimitedError
from infrastructure.cache.cache_keys import (
    LRCLIB_PREFIX,
    lrclib_exact_lyrics_key,
    lrclib_prefixes,
)
from infrastructure.cache.memory_cache import InMemoryCache
from repositories.lrclib_repository import LrclibRepository
from repositories.protocols.lrclib import LrclibRepositoryProtocol

_FIXTURE = (
    Path(__file__).resolve().parents[1] / "fixtures" / "lrclib" / "exact_lyrics.json"
)


@pytest.mark.asyncio
async def test_exact_lookup_uses_live_shape_and_caches(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "repositories.lrclib_repository._lrclib_rate_limiter.acquire", AsyncMock()
    )
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=_FIXTURE.read_bytes(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = InMemoryCache()
        repository = LrclibRepository(client, cache)
        first = await repository.get_exact_lyrics(
            track_name="The Chain",
            artist_name="Fleetwood Mac",
            album_name="Rumours (West German Target CD Master)",
            duration_seconds=270,
        )
        second = await repository.get_exact_lyrics(
            track_name="The Chain",
            artist_name="Fleetwood Mac",
            album_name="Rumours (West German Target CD Master)",
            duration_seconds=270,
        )

    assert len(requests) == 1
    assert requests[0].url.path == "/api/get"
    assert requests[0].url.params["duration"] == "270"
    assert first == second
    assert first.found is True
    assert first.candidate is not None
    assert first.candidate.provider_id == 18514138
    assert first.candidate.plain_lyrics == "First line\nSecond line"
    assert first.candidate.synced_lyrics.startswith("[00:01.00]")
    assert len(first.candidate.provider_revision) == 64
    assert (
        await cache.get(
            lrclib_exact_lyrics_key(
                "The Chain",
                "Fleetwood Mac",
                "Rumours (West German Target CD Master)",
                270,
            )
        )
        == first
    )
    assert lrclib_prefixes() == [LRCLIB_PREFIX]


@pytest.mark.asyncio
async def test_404_is_cached_absence(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "repositories.lrclib_repository._lrclib_rate_limiter.acquire", AsyncMock()
    )
    requests = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal requests
        requests += 1
        return httpx.Response(404, json={"statusCode": 404}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LrclibRepository(client, InMemoryCache())
        values = [
            await repository.get_exact_lyrics(
                track_name="Missing",
                artist_name="Nobody",
                album_name="Nowhere",
                duration_seconds=180,
            )
            for _ in range(2)
        ]

    assert requests == 1
    assert all(value.found is False and value.candidate is None for value in values)


@pytest.mark.asyncio
async def test_invalid_shape_raises_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "repositories.lrclib_repository._lrclib_rate_limiter.acquire", AsyncMock()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"id": "wrong", "trackName": "Track"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LrclibRepository(client, InMemoryCache())
        with pytest.raises(LrclibApiError, match="invalid"):
            await repository.get_exact_lyrics(
                track_name="Track",
                artist_name="Artist",
                album_name="Album",
                duration_seconds=180,
            )


@pytest.mark.asyncio
async def test_oversized_lyrics_raise_typed_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "repositories.lrclib_repository._lrclib_rate_limiter.acquire", AsyncMock()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 1,
                "trackName": "Track",
                "artistName": "Artist",
                "albumName": "Album",
                "duration": 180,
                "instrumental": False,
                "plainLyrics": "x" * 1_000_001,
                "syncedLyrics": None,
            },
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LrclibRepository(client, InMemoryCache())
        with pytest.raises(LrclibApiError, match="oversized lyrics content"):
            await repository.get_exact_lyrics(
                track_name="Track",
                artist_name="Artist",
                album_name="Album",
                duration_seconds=180,
            )


@pytest.mark.asyncio
async def test_429_surfaces_typed_retry_after_without_breaker_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "repositories.lrclib_repository._lrclib_rate_limiter.acquire", AsyncMock()
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, headers={"Retry-After": "7"}, request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = LrclibRepository(client, InMemoryCache())
        with pytest.raises(RateLimitedError) as raised:
            await repository.get_exact_lyrics(
                track_name="Track",
                artist_name="Artist",
                album_name="Album",
                duration_seconds=180,
            )

    assert raised.value.retry_after_seconds == 7.0


def test_repository_conforms_to_protocol() -> None:
    assert inspect.signature(LrclibRepositoryProtocol.get_exact_lyrics) == (
        inspect.signature(LrclibRepository.get_exact_lyrics)
    )

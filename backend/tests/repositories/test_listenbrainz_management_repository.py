import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from core.exceptions import RateLimitedError
from infrastructure.cache.cache_keys import (
    LB_PREFIX,
    listenbrainz_management_genres_key,
    listenbrainz_prefixes,
)
from infrastructure.cache.memory_cache import InMemoryCache
from repositories.listenbrainz_repository import ListenBrainzRepository
from repositories.protocols.listenbrainz_management import (
    ListenBrainzGenreRepositoryProtocol,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "listenbrainz"
    / "management_release_group.json"
)
_RG = "dcff25f1-702d-3b5e-b0da-d48172e6e62a"


@pytest.mark.asyncio
async def test_release_group_genres_use_verified_get_shape_and_cache() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, content=_FIXTURE.read_bytes(), request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = InMemoryCache()
        repository = ListenBrainzRepository(client, cache)
        first = await repository.get_release_group_genres_batch([_RG, _RG])
        second = await repository.get_release_group_genres_batch([_RG])

    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert requests[0].url.path == "/1/metadata/release_group/"
    assert requests[0].url.params["release_group_mbids"] == _RG
    assert requests[0].url.params["inc"] == "artist tag release"
    assert [value.display_name for value in first[_RG]] == [
        "Classical",
        "Keyboard",
        "Baroque",
    ]
    assert first[_RG][0].curated is True
    assert first[_RG][1].curated is False
    assert first[_RG][2].provider_entity == "artist"
    assert second[_RG] == first[_RG]
    assert await cache.get(listenbrainz_management_genres_key(_RG)) == first[_RG]
    assert LB_PREFIX in listenbrainz_prefixes()


@pytest.mark.asyncio
async def test_release_group_genres_bound_get_batches_and_cache_missing_ids() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={}, request=request)

    ids = [f"00000000-0000-4000-8000-{value:012d}" for value in range(26)]
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        cache = InMemoryCache()
        result = await ListenBrainzRepository(
            client, cache
        ).get_release_group_genres_batch(ids)

    assert len(requests) == 2
    assert sorted(
        len(request.url.params["release_group_mbids"].split(","))
        for request in requests
    ) == [1, 25]
    assert set(result) == set(ids)
    assert all(value == () for value in result.values())


@pytest.mark.asyncio
async def test_rate_limit_headers_produce_bounded_retry_hint(monkeypatch) -> None:
    retry_sleep = AsyncMock()
    monkeypatch.setattr("infrastructure.resilience.retry.asyncio.sleep", retry_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            429,
            text="slow down",
            headers={"X-RateLimit-Reset-In": "7"},
            request=request,
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        repository = ListenBrainzRepository(client, InMemoryCache())
        with pytest.raises(RateLimitedError) as raised:
            await repository.get_release_group_genres_batch([_RG])
    assert raised.value.retry_after_seconds == 7
    assert [call.args[0] for call in retry_sleep.await_args_list] == [7, 7]


def test_management_method_conforms_to_narrow_protocol() -> None:
    assert inspect.signature(
        ListenBrainzGenreRepositoryProtocol.get_release_group_genres_batch
    ) == inspect.signature(ListenBrainzRepository.get_release_group_genres_batch)

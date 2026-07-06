"""GeocodingRepository tests - decode of the live-verified Open-Meteo shape,
the no-results-vs-provider-failure distinction (empty [] is only ever 'no such
city'; failures raise), and error mapping."""

import asyncio

import httpx
import pytest

from core.exceptions import GeocodingApiError
from repositories.geocoding_repository import GeocodingRepository

_LIVERPOOL_JSON = b"""
{"results": [{"id": 2644210, "name": "Liverpool", "latitude": 53.41058,
"longitude": -2.97794, "country_code": "GB", "country": "United Kingdom",
"admin1": "England", "population": 496770}]}
"""


class _StubClient:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = responses
        self.calls: list[dict] = []

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.calls.append(dict(params or {}))
        return self._responses.pop(0)


@pytest.fixture(autouse=True)
def _no_real_waits(monkeypatch):
    async def instant(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    from repositories import geocoding_repository as module

    monkeypatch.setattr(module._geocoding_rate_limiter, "acquire", instant)


@pytest.mark.asyncio
async def test_search_decodes_live_shape():
    client = _StubClient([httpx.Response(200, content=_LIVERPOOL_JSON)])
    repo = GeocodingRepository(client)
    results = await repo.search_cities("Liverpool")
    assert len(results) == 1
    city = results[0]
    assert city.name == "Liverpool"
    assert city.latitude == pytest.approx(53.41058)
    assert city.country_code == "GB"
    assert city.admin1 == "England"
    assert client.calls[0]["name"] == "Liverpool"


@pytest.mark.asyncio
async def test_no_results_is_empty_list_not_error():
    # Open-Meteo omits 'results' entirely for unknown places
    client = _StubClient([httpx.Response(200, content=b"{}")])
    assert await GeocodingRepository(client).search_cities("xyzzy") == []


@pytest.mark.asyncio
async def test_non_2xx_raises():
    client = _StubClient([httpx.Response(500)])
    with pytest.raises(GeocodingApiError):
        await GeocodingRepository(client).search_cities("Liverpool")


@pytest.mark.asyncio
async def test_429_maps_to_rate_limited_error():
    from core.exceptions import RateLimitedError

    client = _StubClient([httpx.Response(429) for _ in range(3)])
    with pytest.raises(RateLimitedError):
        await GeocodingRepository(client).search_cities("Liverpool")


@pytest.mark.asyncio
async def test_decode_failure_raises():
    client = _StubClient([httpx.Response(200, content=b"<html>")])
    with pytest.raises(GeocodingApiError):
        await GeocodingRepository(client).search_cities("Liverpool")

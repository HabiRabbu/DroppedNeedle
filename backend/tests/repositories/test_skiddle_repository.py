"""SkiddleRepository tests - decode of live-probed fixtures (string ids,
'0'/'1' cancelled flag, mixed key casing, empty-string absences), the
error!=0-on-HTTP-200 envelope, error mapping, and protocol conformance."""

import asyncio
import inspect
from pathlib import Path

import httpx
import pytest

from core.exceptions import RateLimitedError, SkiddleApiError
from repositories.protocols.skiddle import SkiddleRepositoryProtocol
from repositories.skiddle_repository import SkiddleRepository

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "events"


class _StubClient:
    def __init__(self, responses: list[httpx.Response]):
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.calls.append((url, dict(params or {})))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        return self._responses.pop(0)


def _repo(*responses: httpx.Response) -> tuple[SkiddleRepository, _StubClient]:
    client = _StubClient(list(responses))
    return SkiddleRepository(client, api_key="k"), client


def _fixture_bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


@pytest.fixture(autouse=True)
def _no_real_waits(monkeypatch):
    async def instant(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    from repositories import skiddle_repository as module

    monkeypatch.setattr(module._skiddle_rate_limiter, "acquire", instant)


@pytest.mark.asyncio
async def test_search_artists_decodes_live_fixture():
    repo, client = _repo(httpx.Response(200, content=_fixture_bytes("sk_artists.json")))
    artists = await repo.search_artists("Fontaines")
    # duplicate ids for one act + a tribute near-name, all as returned
    assert [(a.name, a.id) for a in artists] == [
        ("Fontaines CD", "123617147"),
        ("Fontaines D.C.", "123568993"),
        ("Fontaines DC", "123604351"),
    ]
    assert artists[1].spotifyartisturl == artists[2].spotifyartisturl  # dupe signal
    assert client.calls[0][1]["api_key"] == "k"


@pytest.mark.asyncio
async def test_events_for_artist_decodes_live_fixture():
    repo, client = _repo(httpx.Response(200, content=_fixture_bytes("sk_byartist.json")))
    events = await repo.events_for_artist("123568993")
    assert len(events) == 4
    first = events[0]
    assert first.eventname == "Reading Festival"
    assert first.date == "2026-08-27"
    assert first.is_cancelled() is False  # wire value is the string '0'
    assert first.is_rescheduled() is False  # empty string means unset
    assert first.venue.town == "Reading"
    assert first.venue.country == "GB"
    assert first.venue.latitude == pytest.approx(51.456062)  # floats on this API
    assert first.ticket_url == ""  # empty string, caller falls back to link
    assert first.link
    assert client.calls[0][1]["a"] == "123568993"


@pytest.mark.asyncio
async def test_geo_fixture_decodes_including_empty_lineups():
    repo, _ = _repo(httpx.Response(200, content=_fixture_bytes("sk_geo.json")))
    events = await repo.events_for_artist("ignored")
    assert len(events) == 5
    assert any(e.artists == [] for e in events)  # small gigs carry no lineup
    assert any(e.artists and e.artists[0].artistid for e in events)


@pytest.mark.asyncio
async def test_error_envelope_on_http_200_raises():
    repo, _ = _repo(
        httpx.Response(200, content=b'{"error": 1, "errormessage": "bad key"}')
    )
    with pytest.raises(SkiddleApiError, match="bad key"):
        await repo.search_artists("x")


@pytest.mark.asyncio
async def test_429_maps_to_rate_limited_error():
    repo, _ = _repo(*[httpx.Response(429) for _ in range(3)])
    with pytest.raises(RateLimitedError):
        await repo.search_artists("x")


@pytest.mark.asyncio
async def test_non_2xx_raises_api_error_without_retry():
    repo, client = _repo(httpx.Response(500))
    with pytest.raises(SkiddleApiError):
        await repo.events_for_artist("1")
    assert len(client.calls) == 1


@pytest.mark.asyncio
async def test_decode_failure_raises_api_error():
    repo, _ = _repo(httpx.Response(200, content=b"<html>"))
    with pytest.raises(SkiddleApiError):
        await repo.search_artists("x")


def test_repository_conforms_to_protocol():
    for name in ("search_artists", "events_for_artist", "test_connection"):
        proto = getattr(SkiddleRepositoryProtocol, name)
        impl = getattr(SkiddleRepository, name)
        assert inspect.iscoroutinefunction(impl), name
        assert inspect.signature(proto) == inspect.signature(impl), name

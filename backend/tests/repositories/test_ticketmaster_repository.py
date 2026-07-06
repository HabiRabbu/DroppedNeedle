"""TicketmasterRepository tests - decode of live-probed fixtures (tolerant
defaults), pagination follow + truncation warning, 429/non-2xx/decode error
mapping, and protocol signature conformance."""

import asyncio
import inspect
import json
from pathlib import Path

import httpx
import pytest

from core.exceptions import RateLimitedError, TicketmasterApiError
from repositories.protocols.ticketmaster import TicketmasterRepositoryProtocol
from repositories.ticketmaster_repository import TicketmasterRepository

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "events"


class _StubClient:
    """Minimal httpx.AsyncClient stand-in (no HTTP-mocking libraries allowed)."""

    def __init__(self, responses: list[httpx.Response]):
        self._responses = responses
        self.calls: list[tuple[str, dict]] = []

    async def get(self, url: str, params: dict | None = None) -> httpx.Response:
        self.calls.append((url, dict(params or {})))
        if not self._responses:
            raise AssertionError("unexpected extra request")
        return self._responses.pop(0)


def _repo(*responses: httpx.Response) -> tuple[TicketmasterRepository, _StubClient]:
    client = _StubClient(list(responses))
    return TicketmasterRepository(client, api_key="k"), client


def _fixture_bytes(name: str) -> bytes:
    return (_FIXTURES / name).read_bytes()


@pytest.fixture(autouse=True)
def _no_real_waits(monkeypatch):
    async def instant(*_args, **_kwargs):
        return None

    monkeypatch.setattr(asyncio, "sleep", instant)
    from repositories import ticketmaster_repository as module

    monkeypatch.setattr(module._ticketmaster_rate_limiter, "acquire", instant)


@pytest.mark.asyncio
async def test_search_attractions_decodes_live_fixture():
    repo, client = _repo(httpx.Response(200, content=_fixture_bytes("tm_attr.json")))
    attractions = await repo.search_attractions("Fontaines D.C.")
    assert [a.name for a in attractions] == ["Fontaines D.C.", "Fontaines D.C. DJ Set"]
    assert attractions[0].musicbrainz_ids() == ["fd87acc7-e0a0-4a45-bc2a-d2ab5c10be68"]
    assert attractions[1].musicbrainz_ids() == []  # the DJ-set sibling trap
    assert client.calls[0][1]["apikey"] == "k"


@pytest.mark.asyncio
async def test_events_for_attraction_decodes_live_fixture():
    repo, _ = _repo(httpx.Response(200, content=_fixture_bytes("tm_events.json")))
    events = await repo.events_for_attraction("K8vZ9179LP7")
    assert len(events) == 5
    first = events[0]
    assert first.dates.start.local_date == "2026-08-28"
    assert first.dates.status.code == "onsale"
    venue = first.embedded.venues[0]
    assert venue.city.name == "Reading"
    assert venue.country.country_code == "GB"
    assert venue.location.latitude == "51.46368200"  # strings on the wire
    # festival lineup: full attractions list with per-attraction optional MBIDs
    lineup = first.embedded.attractions
    assert len(lineup) > 10
    assert any(a.musicbrainz_ids() for a in lineup)


@pytest.mark.asyncio
async def test_missing_embedded_decodes_as_no_results():
    repo, _ = _repo(httpx.Response(200, content=b'{"page": {"totalPages": 0}}'))
    assert await repo.search_attractions("nobody") == []


@pytest.mark.asyncio
async def test_pagination_follows_next_pages():
    def page(number: int, total_pages: int, event_id: str) -> bytes:
        return json.dumps(
            {
                "_embedded": {"events": [{"id": event_id, "name": event_id}]},
                "page": {"size": 200, "totalElements": 2, "totalPages": total_pages,
                         "number": number},
            }
        ).encode()

    repo, client = _repo(
        httpx.Response(200, content=page(0, 2, "e1")),
        httpx.Response(200, content=page(1, 2, "e2")),
    )
    events = await repo.events_for_attraction("A1")
    assert [e.id for e in events] == ["e1", "e2"]
    assert [c[1]["page"] for c in client.calls] == ["0", "1"]


@pytest.mark.asyncio
async def test_pagination_truncates_at_cap_with_warning(caplog):
    def page(number: int) -> bytes:
        return json.dumps(
            {
                "_embedded": {"events": [{"id": f"e{number}"}]},
                "page": {"totalPages": 10, "number": number},
            }
        ).encode()

    repo, client = _repo(*[httpx.Response(200, content=page(n)) for n in range(3)])
    with caplog.at_level("WARNING"):
        events = await repo.events_for_attraction("A1")
    assert len(events) == 3
    assert len(client.calls) == 3  # hard cap, no 4th request
    assert any("truncated" in r.message for r in caplog.records)


@pytest.mark.asyncio
async def test_429_maps_to_rate_limited_error_with_hint():
    responses = [
        httpx.Response(429, headers={"Retry-After": "7"}) for _ in range(3)
    ]
    repo, _ = _repo(*responses)
    with pytest.raises(RateLimitedError) as excinfo:
        await repo.search_attractions("x")
    assert excinfo.value.retry_after_seconds == 7.0


@pytest.mark.asyncio
async def test_non_2xx_raises_api_error_without_retry():
    repo, client = _repo(httpx.Response(500))
    with pytest.raises(TicketmasterApiError):
        await repo.search_attractions("x")
    assert len(client.calls) == 1  # not retriable


@pytest.mark.asyncio
async def test_decode_failure_raises_api_error():
    repo, _ = _repo(httpx.Response(200, content=b"not json"))
    with pytest.raises(TicketmasterApiError):
        await repo.search_attractions("x")


def test_repository_conforms_to_protocol():
    for name in ("search_attractions", "events_for_attraction", "test_connection"):
        proto = getattr(TicketmasterRepositoryProtocol, name)
        impl = getattr(TicketmasterRepository, name)
        assert inspect.iscoroutinefunction(impl), name
        assert inspect.signature(proto) == inspect.signature(impl), name

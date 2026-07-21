import asyncio
import inspect
from pathlib import Path

import httpx
import pytest

from core.exceptions import RateLimitedError
from infrastructure.cache.memory_cache import InMemoryCache
from infrastructure.queue.priority_queue import RequestPriority
from repositories.discogs.discogs_repository import DiscogsRepository
from repositories.protocols.discogs import DiscogsRepositoryProtocol

_FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "discogs"


class _StubClient:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self.responses = responses
        self.calls: list[tuple[str, dict[str, str]]] = []

    async def get(
        self, url: str, params: dict[str, str] | None = None
    ) -> httpx.Response:
        self.calls.append((url, dict(params or {})))
        if not self.responses:
            raise AssertionError("unexpected extra Discogs request")
        return self.responses.pop(0)


def _repo(*responses: httpx.Response) -> tuple[DiscogsRepository, _StubClient]:
    client = _StubClient(list(responses))
    return DiscogsRepository(client, InMemoryCache()), client


@pytest.fixture(autouse=True)
def _no_wait(monkeypatch):
    async def instant(*_args, **_kwargs) -> None:
        return None

    from repositories.discogs import discogs_repository as module

    monkeypatch.setattr(asyncio, "sleep", instant)
    monkeypatch.setattr(module._discogs_rate_limiter, "acquire", instant)
    module.DiscogsRepository.reset_circuit_breaker()


@pytest.mark.asyncio
async def test_exact_release_normalizes_only_contribution_metadata() -> None:
    repo, client = _repo(
        httpx.Response(200, content=(_FIXTURES / "release_249504.json").read_bytes())
    )
    release = await repo.get_release("249504", priority=RequestPriority.USER_INITIATED)
    assert release is not None
    assert release.release_id == "249504"
    assert release.master_id == "96559"
    assert release.barcode == "5012394144777"
    assert [track.source_position for track in release.media[0].tracks] == ["A", "B"]
    assert release.media[0].tracks[0].duration_seconds == 212
    assert "images" not in repr(release)
    assert "community" not in repr(release)
    assert client.calls[0][0] == "https://api.discogs.com/releases/249504"


@pytest.mark.asyncio
async def test_search_normalizes_results_and_uses_cache() -> None:
    repo, client = _repo(
        httpx.Response(200, content=(_FIXTURES / "search_releases.json").read_bytes())
    )
    first = await repo.search_releases(
        "Rick Astley", priority=RequestPriority.USER_INITIATED, limit=8
    )
    second = await repo.search_releases(
        " Rick   Astley ", priority=RequestPriority.USER_INITIATED, limit=8
    )
    assert first == second
    assert len(client.calls) == 1
    assert first[0].title == "Never Gonna Give You Up"
    assert first[0].canonical_url == "https://www.discogs.com/release/249504"


@pytest.mark.asyncio
async def test_absence_and_decode_failure_are_softened() -> None:
    missing, _ = _repo(httpx.Response(404))
    invalid, _ = _repo(httpx.Response(200, content=b"not-json"))
    assert (
        await missing.get_release("1", priority=RequestPriority.USER_INITIATED) is None
    )
    assert (
        await invalid.get_release("2", priority=RequestPriority.USER_INITIATED) is None
    )


@pytest.mark.asyncio
async def test_rate_limit_remains_actionable() -> None:
    repo, _ = _repo(
        *[httpx.Response(429, headers={"Retry-After": "7"}) for _ in range(3)]
    )
    with pytest.raises(RateLimitedError) as error:
        await repo.get_release("1", priority=RequestPriority.USER_INITIATED)
    assert error.value.retry_after_seconds == 7


def test_repository_conforms_to_protocol() -> None:
    for name in ("get_release", "search_releases"):
        assert inspect.signature(
            getattr(DiscogsRepositoryProtocol, name)
        ) == inspect.signature(getattr(DiscogsRepository, name))

import asyncio
import inspect
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import msgspec
import pytest

from core.exceptions import ExternalServiceError
from infrastructure.cache.cache_keys import (
    MB_MANAGEMENT_RELEASE_PREFIX,
    mb_management_release_key,
    musicbrainz_prefixes,
)
from infrastructure.queue.priority_queue import RequestPriority
from infrastructure.resilience.retry import CircuitOpenError
from repositories.musicbrainz_album import MusicBrainzAlbumMixin
from repositories.musicbrainz_management_models import MbManagementRelease
from repositories.musicbrainz_repository import MusicBrainzRepository
from repositories.protocols.musicbrainz_management import (
    CanonicalMusicBrainzRepositoryProtocol,
)

_FIXTURE = (
    Path(__file__).resolve().parents[1]
    / "fixtures"
    / "musicbrainz"
    / "management_release.json"
)


class _Repo(MusicBrainzAlbumMixin):
    def __init__(self) -> None:
        self._cache = AsyncMock()
        self._cache.get.return_value = None


def _release() -> MbManagementRelease:
    return msgspec.json.decode(_FIXTURE.read_bytes(), type=MbManagementRelease)


def test_verified_fixture_decodes_full_management_surface_tolerantly() -> None:
    release = _release()
    track = release.media[0].tracks[0]
    recording = track.recording
    performance = recording.relations[1]

    assert release.date == "1982-10"
    assert release.release_group.first_release_date == "1956"
    assert release.artist_credit[0].artist.sort_name == "Bach, Johann Sebastian"
    assert release.artist_credit[0].artist.aliases[0].locale == "en"
    assert release.release_group.aliases[0].name == "Variaciones Goldberg"
    assert release.label_info[0].catalog_number == "M2K 52648"
    assert release.label_info[1].label is None
    assert release.media[0].format == "CD"
    assert release.media[0].title == "Aria and Variations"
    assert track.id == "22222222-2222-4222-8222-222222222222"
    assert recording.id == "33333333-3333-4333-8333-333333333333"
    assert recording.isrcs == ["USSM18200001"]
    assert recording.genres[0].count == 3
    assert performance.work is not None
    assert performance.work.relations[0].type == "composer"


def test_partial_provider_document_uses_tolerant_defaults() -> None:
    release = msgspec.json.decode(b'{"id":"release-id"}', type=MbManagementRelease)
    assert release.id == "release-id"
    assert release.media == []
    assert release.artist_credit == []
    assert release.release_group.id == ""
    assert release.text_representation.language is None


@pytest.mark.asyncio
async def test_fetch_uses_sorted_includes_priority_and_projection_cache_inputs(
    monkeypatch,
) -> None:
    import repositories.musicbrainz_album as module

    api = AsyncMock(return_value=_release())
    monkeypatch.setattr(module, "mb_api_get", api)
    repo = _Repo()

    result = await repo.get_canonical_release(
        "aff0622e-7bd3-4fb6-9ca3-0fa19dd2340b",
        includes=("recordings", "aliases", "recordings", "artist-credits"),
        preferred_locales=("en-GB", "ja"),
        artist_standardization="variations",
        priority=RequestPriority.BACKGROUND_SYNC,
    )

    assert result is not None
    assert api.await_args.kwargs["params"] == {
        "inc": "aliases+artist-credits+recordings"
    }
    assert api.await_args.kwargs["priority"] is RequestPriority.BACKGROUND_SYNC
    assert api.await_args.kwargs["decode_type"] is MbManagementRelease
    cache_key = repo._cache.set.await_args.args[0]
    assert "locales=en-gb,ja" in cache_key
    assert "artists=variations" in cache_key


@pytest.mark.asyncio
async def test_successful_result_is_read_from_cache(monkeypatch) -> None:
    import repositories.musicbrainz_album as module

    api = AsyncMock()
    monkeypatch.setattr(module, "mb_api_get", api)
    repo = _Repo()
    repo._cache.get.return_value = _release()

    result = await repo.get_canonical_release("release-id", includes=("recordings",))
    assert result is repo._cache.get.return_value
    api.assert_not_awaited()


@pytest.mark.asyncio
async def test_definitive_missing_release_is_negative_cached(monkeypatch) -> None:
    import repositories.musicbrainz_album as module

    api = AsyncMock(return_value=MbManagementRelease())
    monkeypatch.setattr(module, "mb_api_get", api)
    repo = _Repo()

    assert await repo.get_canonical_release("missing", includes=("recordings",)) is None
    assert repo._cache.set.await_args.args[1] is False
    assert repo._cache.set.await_args.kwargs["ttl_seconds"] == 600


@pytest.mark.parametrize(
    "failure",
    [
        httpx.ConnectError("connection failed"),
        CircuitOpenError("circuit open", "musicbrainz"),
        ExternalServiceError("provider returned 503"),
    ],
)
@pytest.mark.asyncio
async def test_provider_outage_is_required_input_failure(
    monkeypatch, failure: Exception
) -> None:
    import repositories.musicbrainz_album as module

    monkeypatch.setattr(module, "mb_api_get", AsyncMock(side_effect=failure))
    with pytest.raises(ExternalServiceError, match="temporarily unavailable"):
        await _Repo().get_canonical_release(
            "release-id", includes=("recordings",), bypass_cache=True
        )


@pytest.mark.asyncio
async def test_identical_requests_are_deduplicated(monkeypatch) -> None:
    import repositories.musicbrainz_album as module

    started = asyncio.Event()
    release_request = asyncio.Event()

    async def load(*_args, **_kwargs):
        started.set()
        await release_request.wait()
        return _release()

    api = AsyncMock(side_effect=load)
    monkeypatch.setattr(module, "mb_api_get", api)
    repo = _Repo()
    first = asyncio.create_task(
        repo.get_canonical_release("release-id", includes=("recordings",))
    )
    await started.wait()
    second = asyncio.create_task(
        repo.get_canonical_release("release-id", includes=("recordings",))
    )
    await asyncio.sleep(0)
    release_request.set()
    await asyncio.gather(first, second)
    assert api.await_count == 1


def test_cache_key_and_invalidation_contract() -> None:
    first = mb_management_release_key(
        "release", ("recordings", "aliases"), ("EN-gb", "ja"), "Canonical"
    )
    second = mb_management_release_key(
        "release", ("aliases", "recordings"), ("EN-gb", "ja"), "Canonical"
    )
    changed_locale_order = mb_management_release_key(
        "release", ("aliases", "recordings"), ("ja", "EN-gb"), "Canonical"
    )
    assert first == second
    assert first != changed_locale_order
    assert MB_MANAGEMENT_RELEASE_PREFIX in musicbrainz_prefixes()


def test_management_method_conforms_to_narrow_protocol() -> None:
    assert inspect.signature(
        CanonicalMusicBrainzRepositoryProtocol.get_canonical_release
    ) == inspect.signature(MusicBrainzRepository.get_canonical_release)

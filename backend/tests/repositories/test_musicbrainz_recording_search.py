"""Tests for MusicBrainzAlbumMixin.search_recordings."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from repositories.musicbrainz_album import (
    MusicBrainzAlbumMixin,
    RecordingMatch,
    _RecordingSearchPayload,
    _pick_best_release_group,
)


class _Repo(MusicBrainzAlbumMixin):
    def __init__(self) -> None:
        self._cache = AsyncMock()
        self._cache.get = AsyncMock(return_value=None)
        self._cache.set = AsyncMock()
        self._preferences_service = SimpleNamespace(
            get_advanced_settings=lambda: SimpleNamespace(cache_ttl_search=3600)
        )


_PAYLOAD = _RecordingSearchPayload(
    recordings=[
        {
            "id": "rec-sad",
            "title": "SAD!",
            "score": 100,
            "artist-credit": [
                {"name": "XXXTENTACION", "artist": {"name": "XXXTENTACION"}}
            ],
            "releases": [
                {
                    "id": "rel-q",
                    "title": "?",
                    "release-group": {
                        "id": "rg-q",
                        "title": "?",
                        "primary-type": "Album",
                    },
                }
            ],
        },
        {
            "id": "rec-sad-2",
            "title": "SAD!",
            "score": 100,
            "artist-credit": [
                {"name": "XXXTENTACION", "artist": {"name": "XXXTENTACION"}}
            ],
            "releases": [
                {
                    "id": "rel-mega",
                    "title": "Mega Hits 2018",
                    "release-group": {
                        "id": "rg-mega",
                        "title": "Mega Hits 2018",
                        "primary-type": "Album",
                        "secondary-types": ["Compilation"],
                    },
                },
                {
                    "id": "rel-mega-2",
                    "title": "Mega Hits 2018 (dupe RG)",
                    "release-group": {
                        "id": "rg-mega",
                        "title": "Mega Hits 2018",
                        "primary-type": "Album",
                        "secondary-types": ["Compilation"],
                    },
                },
            ],
        },
    ]
)


@pytest.mark.asyncio
async def test_search_recordings_parses_and_dedupes_release_groups():
    with patch(
        "repositories.musicbrainz_album.mb_api_get", AsyncMock(return_value=_PAYLOAD)
    ) as mock_get:
        matches = await _Repo().search_recordings("XXXTENTACION", "SAD!")

    assert mock_get.await_args.kwargs["params"]["query"] == (
        'recording:"SAD!" AND artist:"XXXTENTACION"'
    )
    assert [m.recording_mbid for m in matches] == ["rec-sad", "rec-sad-2"]

    first = matches[0]
    assert isinstance(first, RecordingMatch)
    assert first.artist == "XXXTENTACION"
    assert first.score == 100
    assert [rg.release_group_mbid for rg in first.release_groups] == ["rg-q"]
    assert first.release_groups[0].release_mbid == "rel-q"
    assert first.release_groups[0].secondary_types == ()

    second = matches[1]
    assert [rg.release_group_mbid for rg in second.release_groups] == ["rg-mega"]
    assert second.release_groups[0].secondary_types == ("Compilation",)


@pytest.mark.asyncio
async def test_search_recordings_blank_inputs_short_circuit():
    repo = _Repo()
    with patch("repositories.musicbrainz_album.mb_api_get", AsyncMock()) as mock_get:
        assert await repo.search_recordings("", "SAD!") == []
        assert await repo.search_recordings("Artist", "   ") == []
    mock_get.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_recordings_uses_cache_when_present():
    repo = _Repo()
    cached = [
        RecordingMatch(
            recording_mbid="r", title="t", artist="a", score=1, release_groups=[]
        )
    ]
    repo._cache.get = AsyncMock(return_value=cached)
    with patch("repositories.musicbrainz_album.mb_api_get", AsyncMock()) as mock_get:
        assert await repo.search_recordings("Artist", "Title") is cached
    mock_get.assert_not_awaited()


def test_include_all_types_bypasses_secondary_type_filter():
    repo = _Repo()
    comp = {
        "id": "rg-comp",
        "title": "Sittin' by the Road",
        "primary-type": "Album",
        "secondary-types": ["Compilation"],
    }
    assert repo._map_release_group_to_result(comp) is None
    mapped = repo._map_release_group_to_result(comp, include_all_types=True)
    assert mapped is not None
    assert mapped.musicbrainz_id == "rg-comp"


@pytest.mark.parametrize("reverse", [False, True])
def test_recording_fallback_prefers_official_compilation_over_bootleg_live(
    reverse: bool,
) -> None:
    releases = [
        {
            "id": "release-live",
            "status": "Bootleg",
            "date": "2019",
            "release-group": {
                "id": "rg-live",
                "title": "Festival 2019",
                "primary-type": "Album",
                "secondary-types": ["Live"],
            },
        },
        {
            "id": "release-compilation",
            "status": "Official",
            "date": "2009-10-30",
            "release-group": {
                "id": "rg-compilation",
                "title": "Greatest Hits",
                "primary-type": "Album",
                "secondary-types": ["Compilation"],
            },
        },
    ]
    if reverse:
        releases.reverse()

    assert _pick_best_release_group(releases) == (
        "rg-compilation",
        "Greatest Hits",
    )


def test_recording_fallback_keeps_bootleg_live_when_it_is_the_only_choice() -> None:
    release = {
        "id": "release-live",
        "status": "Bootleg",
        "release-group": {
            "id": "rg-live",
            "title": "Festival 2019",
            "primary-type": "Album",
            "secondary-types": ["Live"],
        },
    }

    assert _pick_best_release_group([release]) == ("rg-live", "Festival 2019")

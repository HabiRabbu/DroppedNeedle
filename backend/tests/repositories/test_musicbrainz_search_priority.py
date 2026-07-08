"""MusicBrainzAlbumMixin.search_albums / search_recordings honour the request priority.

The scan path passes ``BACKGROUND_SYNC`` so a library refresh yields to live user searches
on the shared 1/s MusicBrainz limiter; every other (user-facing) caller keeps the
``USER_INITIATED`` default. These assert the param is threaded to ``mb_api_get`` unchanged.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from infrastructure.queue.priority_queue import RequestPriority
from repositories.musicbrainz_album import (
    MusicBrainzAlbumMixin,
    _RecordingSearchPayload,
    _ReleaseGroupSearchPayload,
)


class _Repo(MusicBrainzAlbumMixin):
    def __init__(self) -> None:
        self._cache = AsyncMock()
        self._cache.get = AsyncMock(return_value=None)
        self._cache.set = AsyncMock()
        self._preferences_service = SimpleNamespace(
            get_advanced_settings=lambda: SimpleNamespace(cache_ttl_search=3600)
        )


@pytest.mark.asyncio
async def test_search_albums_defaults_to_user_initiated():
    with patch(
        "repositories.musicbrainz_album.mb_api_get",
        AsyncMock(return_value=_ReleaseGroupSearchPayload()),
    ) as mock_get:
        await _Repo().search_albums("query")
    assert mock_get.await_args.kwargs["priority"] == RequestPriority.USER_INITIATED


@pytest.mark.asyncio
async def test_search_albums_forwards_background_priority():
    with patch(
        "repositories.musicbrainz_album.mb_api_get",
        AsyncMock(return_value=_ReleaseGroupSearchPayload()),
    ) as mock_get:
        await _Repo().search_albums("query", priority=RequestPriority.BACKGROUND_SYNC)
    assert mock_get.await_args.kwargs["priority"] == RequestPriority.BACKGROUND_SYNC


@pytest.mark.asyncio
async def test_search_recordings_defaults_to_user_initiated():
    with patch(
        "repositories.musicbrainz_album.mb_api_get",
        AsyncMock(return_value=_RecordingSearchPayload()),
    ) as mock_get:
        await _Repo().search_recordings("artist", "title")
    assert mock_get.await_args.kwargs["priority"] == RequestPriority.USER_INITIATED


@pytest.mark.asyncio
async def test_search_recordings_forwards_background_priority():
    with patch(
        "repositories.musicbrainz_album.mb_api_get",
        AsyncMock(return_value=_RecordingSearchPayload()),
    ) as mock_get:
        await _Repo().search_recordings(
            "artist", "title", priority=RequestPriority.BACKGROUND_SYNC
        )
    assert mock_get.await_args.kwargs["priority"] == RequestPriority.BACKGROUND_SYNC

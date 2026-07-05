"""SpotifyImportService unit tests (PR #108).

Covers the linking gate, the owned-playlist filtering + imported-mapping in
``list_playlists``, the empty-playlist populate path, and the cover-image picker.
The Spotify client and the async playlist repo are mocked, so no network or DB.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.spotify_import_service import (
    SpotifyImportService,
    SpotifyNotLinkedError,
    _best_image_url,
)


def _service(client) -> SpotifyImportService:
    factory = AsyncMock()
    factory.resolve_spotify = AsyncMock(return_value=client)
    return SpotifyImportService(
        client_factory=factory,
        playlist_repo=MagicMock(),
        mb_repo=AsyncMock(),
        playlist_service=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_list_playlists_raises_when_not_linked():
    svc = _service(client=None)  # resolve_spotify returns None -> not linked
    with pytest.raises(SpotifyNotLinkedError):
        await svc.list_playlists("user-1")


@pytest.mark.asyncio
async def test_list_playlists_filters_to_owned_and_marks_imported():
    client = AsyncMock()
    client.spotify_user_id = "spot-me"
    client.get_user_playlists = AsyncMock(
        return_value=[
            {
                "id": "p1",
                "name": "Mine",
                "description": "",
                "owner": {"id": "spot-me", "display_name": "Me"},
                "images": [{"url": "cover-1", "width": 300}],
                "tracks": {"total": 5},
            },
            {
                "id": "p2",
                "name": "Someone else's",
                "owner": {"id": "other-user"},
                "tracks": {"total": 2},
            },
        ]
    )
    svc = _service(client)
    # p1 was already imported as internal playlist 'int-1'.
    svc._async_repo = AsyncMock()
    svc._async_repo.get_all_playlists = AsyncMock(
        return_value=[SimpleNamespace(id="int-1", source_ref="spotify:p1")]
    )

    result = await svc.list_playlists("user-1")

    # p2 is owned by another Spotify user -> filtered out.
    assert [p["id"] for p in result] == ["p1"]
    assert result[0]["imported_playlist_id"] == "int-1"
    assert result[0]["track_count"] == 5
    assert result[0]["cover_url"] == "cover-1"


@pytest.mark.asyncio
async def test_populate_playlist_with_no_tracks_writes_empty():
    client = AsyncMock()
    client.get_playlist = AsyncMock(return_value={"id": "p1", "name": "Empty"})
    client.get_playlist_tracks = AsyncMock(return_value=[])
    svc = _service(client)
    svc._async_repo = AsyncMock()
    svc._async_repo.get_tracks = AsyncMock(return_value=[])
    svc._async_repo.add_tracks = AsyncMock()

    await svc.populate_playlist("user-1", "p1", "int-1")

    # No tracks resolved -> no MusicBrainz calls, and an empty track list is written.
    svc._mb_repo.resolve_recording_to_release_group.assert_not_awaited()
    svc._async_repo.add_tracks.assert_awaited_once_with("int-1", [])


def test_best_image_url_prefers_smallest_at_or_above_min():
    images = [
        {"url": "tiny", "width": 64},
        {"url": "huge", "width": 640},
        {"url": "mid", "width": 300},
    ]
    assert _best_image_url(images, min_size=250) == "mid"


def test_best_image_url_falls_back_to_largest_when_all_below_min():
    images = [{"url": "a", "width": 60}, {"url": "b", "width": 120}]
    assert _best_image_url(images, min_size=250) == "b"


def test_best_image_url_none_when_empty():
    assert _best_image_url([]) is None

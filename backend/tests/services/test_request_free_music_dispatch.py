"""RequestService picks the dispatcher: a user-configured download client if one
exists, otherwise Free Music (D24). After 2.0 removes slskd and Usenet, Free
Music is the only path."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from services.request_service import RequestService


def _service(*, builtin_ready: bool, free_music_ready: bool = True):
    history = AsyncMock()
    history.async_get_record = AsyncMock(return_value=None)
    history.async_record_request = AsyncMock()
    history.async_update_download_task_id = AsyncMock()
    history.async_update_status = AsyncMock()

    download = MagicMock()
    download.request_album = AsyncMock(return_value="slskd-task")
    free_music = MagicMock()
    free_music.is_ready = MagicMock(return_value=free_music_ready)
    free_music.request_album = AsyncMock(return_value="free-task")

    prefs = SimpleNamespace(is_builtin_download_ready=lambda: builtin_ready)

    service = RequestService(
        history,
        get_download_service=lambda: download,
        quota_service=None,
        get_free_music_service=lambda: free_music,
        preferences_service=prefs,
    )
    return service, download, free_music, history


@pytest.mark.asyncio
async def test_free_music_serves_the_request_when_no_client_is_configured():
    service, download, free_music, history = _service(builtin_ready=False)

    result = await service.request_album(
        "d0484284-1ee7-4157-951a-50f003cbcfb4",
        artist="Brad Sucks",
        album="Guess Who's a Mess",
        user_id="u1",
        user_role="admin",
    )

    assert result.success is True
    free_music.request_album.assert_awaited_once()
    download.request_album.assert_not_awaited()
    history.async_update_download_task_id.assert_awaited_once()
    assert history.async_update_download_task_id.await_args.args[1] == "free-task"


@pytest.mark.asyncio
async def test_a_configured_client_still_wins():
    service, download, free_music, _ = _service(builtin_ready=True)

    await service.request_album(
        "rg-1", artist="A", album="B", user_id="u1", user_role="admin"
    )

    download.request_album.assert_awaited_once()
    free_music.request_album.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_free_music_falls_back_to_the_builtin_dispatcher():
    service, download, free_music, _ = _service(builtin_ready=False, free_music_ready=False)

    await service.request_album(
        "rg-1", artist="A", album="B", user_id="u1", user_role="admin"
    )

    download.request_album.assert_awaited_once()
    free_music.request_album.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_plain_users_request_still_awaits_approval():
    service, download, free_music, _ = _service(builtin_ready=False)

    result = await service.request_album(
        "rg-1", artist="A", album="B", user_id="u1", user_role="user"
    )

    assert result.status == "awaiting_approval"
    free_music.request_album.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_uses_free_music_when_no_client_is_configured():
    """A batch request must pick the same dispatcher as a single one, or every item
    silently fails on a Free-Music-only box while single requests work."""
    service, download, free_music, history = _service(builtin_ready=False)
    history.async_get_active_mbids = AsyncMock(return_value=set())
    history.async_bulk_record_requests = AsyncMock()

    items = [
        {"musicbrainz_id": "rg-1", "artist_name": "A", "album_title": "One"},
        {"musicbrainz_id": "rg-2", "artist_name": "B", "album_title": "Two"},
    ]
    result = await service.request_batch(items, user_id="u1", user_role="admin")

    assert result.success is True
    assert free_music.request_album.await_count == 2
    download.request_album.assert_not_awaited()


@pytest.mark.asyncio
async def test_batch_uses_the_builtin_client_when_one_is_configured():
    service, download, free_music, history = _service(builtin_ready=True)
    history.async_get_active_mbids = AsyncMock(return_value=set())
    history.async_bulk_record_requests = AsyncMock()

    items = [{"musicbrainz_id": "rg-1", "artist_name": "A", "album_title": "One"}]
    await service.request_batch(items, user_id="u1", user_role="admin")

    download.request_album.assert_awaited_once()
    free_music.request_album.assert_not_awaited()

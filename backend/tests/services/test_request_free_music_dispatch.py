"""RequestService delegates every auto-approved dispatch to the AcquisitionDispatcher
(which chooses the client vs Free Music). The choice logic itself is covered by
test_acquisition_dispatcher.py; here we prove RequestService routes single and batch
requests through it, and still gates plain-user requests behind approval."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from services.request_service import RequestService


def _service():
    history = AsyncMock()
    history.async_get_record = AsyncMock(return_value=None)
    history.async_record_request = AsyncMock()
    history.async_update_download_task_id = AsyncMock()
    history.async_update_status = AsyncMock()
    history.async_get_active_mbids = AsyncMock(return_value=set())
    history.async_bulk_record_requests = AsyncMock()

    download = MagicMock()
    acquisition = MagicMock()
    acquisition.request_album = AsyncMock(return_value="task-1")

    service = RequestService(
        history,
        get_download_service=lambda: download,
        quota_service=None,
        acquisition=acquisition,
    )
    return service, acquisition, history


@pytest.mark.asyncio
async def test_single_request_delegates_to_the_dispatcher():
    service, acquisition, history = _service()

    result = await service.request_album(
        "d0484284-1ee7-4157-951a-50f003cbcfb4",
        artist="Brad Sucks", album="Guess Who's a Mess", user_id="u1", user_role="admin",
    )

    assert result.success is True
    acquisition.request_album.assert_awaited_once()
    history.async_update_download_task_id.assert_awaited_once()
    assert history.async_update_download_task_id.await_args.args[1] == "task-1"


@pytest.mark.asyncio
async def test_batch_delegates_each_item_to_the_dispatcher():
    service, acquisition, _ = _service()

    items = [
        {"musicbrainz_id": "rg-1", "artist_name": "A", "album_title": "One"},
        {"musicbrainz_id": "rg-2", "artist_name": "B", "album_title": "Two"},
    ]
    result = await service.request_batch(items, user_id="u1", user_role="admin")

    assert result.success is True
    assert acquisition.request_album.await_count == 2


@pytest.mark.asyncio
async def test_a_plain_users_request_still_awaits_approval():
    service, acquisition, _ = _service()

    result = await service.request_album(
        "rg-1", artist="A", album="B", user_id="u1", user_role="user"
    )

    assert result.status == "awaiting_approval"
    acquisition.request_album.assert_not_awaited()

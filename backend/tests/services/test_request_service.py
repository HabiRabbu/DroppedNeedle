from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from core.exceptions import ExternalServiceError
from services.request_service import RequestService


def _make_service() -> tuple[RequestService, MagicMock, MagicMock]:
    request_history = MagicMock()
    download_service = MagicMock()

    request_history.async_record_request = AsyncMock()
    request_history.async_get_record = AsyncMock(return_value=None)
    request_history.async_update_status = AsyncMock()
    request_history.async_update_download_task_id = AsyncMock()
    request_history.async_bulk_record_requests = AsyncMock()
    request_history.async_get_active_mbids = AsyncMock(return_value=set())
    download_service.request_album = AsyncMock(return_value="task-1")
    download_service.cancel_task = AsyncMock()

    service = RequestService(request_history, download_service)
    return service, request_history, download_service


@pytest.mark.asyncio
async def test_request_album_dispatches_download_and_links_task():
    service, request_history, download_service = _make_service()

    response = await service.request_album(
        "rg-123", artist="Fallback Artist", album="Fallback Album", year=2024, user_role="admin"
    )

    assert response.success is True
    assert response.message == "Request accepted"
    assert response.musicbrainz_id == "rg-123"
    assert response.status == "pending"

    download_service.request_album.assert_awaited_once()
    request_history.async_update_download_task_id.assert_awaited_once_with("rg-123", "task-1")
    request_history.async_record_request.assert_awaited_once()
    kwargs = request_history.async_record_request.await_args.kwargs
    assert kwargs["artist_name"] == "Fallback Artist"
    assert kwargs["album_title"] == "Fallback Album"


@pytest.mark.asyncio
async def test_request_album_user_role_awaits_approval_without_dispatch():
    service, request_history, download_service = _make_service()

    response = await service.request_album("rg-123", user_role="user")

    assert response.status == "awaiting_approval"
    download_service.request_album.assert_not_awaited()
    request_history.async_update_download_task_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_album_already_in_library_not_linked_as_task_id():
    service, request_history, download_service = _make_service()
    download_service.request_album = AsyncMock(return_value="already_in_library")

    response = await service.request_album("rg-123", user_role="admin")

    assert response.success is True
    assert response.message == "Album is already in the library"
    request_history.async_update_download_task_id.assert_not_awaited()


@pytest.mark.asyncio
async def test_request_album_wraps_errors():
    service, _request_history, download_service = _make_service()
    download_service.request_album = AsyncMock(side_effect=RuntimeError("boom"))

    with pytest.raises(ExternalServiceError):
        await service.request_album("rg-123", user_role="admin")


@pytest.mark.asyncio
async def test_request_batch_dispatches_each_and_links():
    service, request_history, download_service = _make_service()
    items = [
        {"musicbrainz_id": "rg-1", "artist_name": "A", "album_title": "B", "year": 2020},
        {"musicbrainz_id": "rg-2", "artist_name": "C", "album_title": "D", "year": 2021},
    ]
    download_service.request_album = AsyncMock(side_effect=["task-1", "task-2"])

    resp = await service.request_batch(items, user_role="admin", user_id="u1")

    assert resp.requested == 2
    assert resp.overflow == 0
    assert download_service.request_album.await_count == 2
    request_history.async_bulk_record_requests.assert_awaited_once()
    linked = {c.args[0]: c.args[1] for c in request_history.async_update_download_task_id.await_args_list}
    assert linked == {"rg-1": "task-1", "rg-2": "task-2"}


@pytest.mark.asyncio
async def test_request_batch_user_role_awaits_approval_without_dispatch():
    service, _request_history, download_service = _make_service()
    items = [{"musicbrainz_id": "rg-1", "artist_name": "A", "album_title": "B", "year": 2020}]

    resp = await service.request_batch(items, user_role="user", user_id="u1")

    assert "approval" in resp.message.lower()
    download_service.request_album.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_batch_admin_cancels_all():
    service, request_history, download_service = _make_service()
    request_history.async_update_status = AsyncMock()
    request_history.async_get_record = AsyncMock(
        return_value=SimpleNamespace(user_id="bob", download_task_id=None)
    )

    response = await service.cancel_batch(["rg-1", "rg-2"], user_id=None, user_role="admin")

    assert response.cancelled == 2
    assert response.failed == 0
    assert response.success is True
    download_service.cancel_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_batch_cancels_linked_native_task():
    service, request_history, download_service = _make_service()
    request_history.async_update_status = AsyncMock()
    request_history.async_get_record = AsyncMock(
        return_value=SimpleNamespace(user_id="alice", download_task_id="task-9")
    )

    response = await service.cancel_batch(["rg-mine"], user_id="alice")

    assert response.cancelled == 1
    download_service.cancel_task.assert_awaited_once_with("task-9", "alice", "user")


@pytest.mark.asyncio
async def test_cancel_batch_user_only_cancels_owned_requests():
    service, request_history, download_service = _make_service()
    request_history.async_update_status = AsyncMock()
    records = {
        "rg-mine": SimpleNamespace(user_id="alice", download_task_id=None),
        "rg-theirs": SimpleNamespace(user_id="bob", download_task_id=None),
    }
    request_history.async_get_record = AsyncMock(side_effect=lambda mbid: records.get(mbid))

    response = await service.cancel_batch(["rg-mine", "rg-theirs"], user_id="alice")

    assert response.cancelled == 1
    assert response.failed == 1
    download_service.cancel_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_cancel_batch_user_missing_record_counts_as_failed():
    service, request_history, _download = _make_service()
    request_history.async_update_status = AsyncMock()
    request_history.async_get_record = AsyncMock(return_value=None)

    response = await service.cancel_batch(["rg-unknown"], user_id="alice")

    assert response.cancelled == 0
    assert response.failed == 1
    assert response.success is False

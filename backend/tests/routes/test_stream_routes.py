from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.responses import Response, StreamingResponse

from api.v1.routes.stream import router
from core.dependencies import get_jellyfin_playback_service
from core.exceptions import ExternalServiceError, PlaybackNotAllowedError, ResourceNotFoundError
from tests.helpers import override_user_auth


async def _fake_body():
    yield b"audio-data-chunk-1"
    yield b"audio-data-chunk-2"


@pytest.fixture
def mock_playback_service():
    mock = MagicMock()
    mock.start_playback = AsyncMock(return_value="sess-start")
    mock.proxy_head = AsyncMock(
        return_value=Response(
            status_code=200,
            headers={
                "Content-Type": "audio/flac",
                "Content-Length": "12345678",
                "Accept-Ranges": "bytes",
            },
        )
    )
    mock.proxy_stream = AsyncMock(
        return_value=StreamingResponse(
            content=_fake_body(),
            status_code=200,
            headers={"Content-Type": "audio/flac", "Content-Length": "12345678"},
            media_type="audio/flac",
        )
    )
    return mock


@pytest.fixture
def client(mock_playback_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_jellyfin_playback_service] = lambda: mock_playback_service
    override_user_auth(app)
    return TestClient(app)


def test_get_stream_returns_proxied_audio(client, mock_playback_service):
    response = client.get("/stream/jellyfin/item-1")

    assert response.status_code == 200
    assert b"audio-data-chunk" in response.content
    mock_playback_service.proxy_stream.assert_awaited_once()
    call_args = mock_playback_service.proxy_stream.call_args
    assert call_args[0][0] == "item-1"


def test_get_stream_forwards_range_header(client, mock_playback_service):
    client.get("/stream/jellyfin/item-1", headers={"Range": "bytes=1000-"})

    call_args = mock_playback_service.proxy_stream.call_args
    assert call_args[1]["range_header"] == "bytes=1000-"


def test_get_stream_returns_404_when_item_missing(client, mock_playback_service):
    mock_playback_service.proxy_stream.side_effect = ResourceNotFoundError("missing")

    response = client.get("/stream/jellyfin/missing-item")

    assert response.status_code == 404


def test_get_stream_returns_403_when_playback_not_allowed(client, mock_playback_service):
    mock_playback_service.proxy_stream.side_effect = PlaybackNotAllowedError("NotAllowed")

    response = client.get("/stream/jellyfin/item-denied")

    assert response.status_code == 403


def test_get_stream_returns_502_on_external_error(client, mock_playback_service):
    mock_playback_service.proxy_stream.side_effect = ExternalServiceError("jellyfin down")

    response = client.get("/stream/jellyfin/item-err")

    assert response.status_code == 502


def test_get_stream_returns_416_on_range_error(client, mock_playback_service):
    mock_playback_service.proxy_stream.side_effect = ExternalServiceError("416 Range not satisfiable")

    response = client.get("/stream/jellyfin/item-range", headers={"Range": "bytes=999999999-"})

    assert response.status_code == 416


def test_head_stream_returns_proxied_headers(client, mock_playback_service):
    response = client.request("HEAD", "/stream/jellyfin/item-1")

    assert response.status_code == 200
    mock_playback_service.proxy_head.assert_awaited_once_with("item-1")


def test_head_stream_returns_404_when_missing(client, mock_playback_service):
    mock_playback_service.proxy_head.side_effect = ResourceNotFoundError("missing")

    response = client.request("HEAD", "/stream/jellyfin/missing-item")

    assert response.status_code == 404


def test_head_stream_returns_403_when_not_allowed(client, mock_playback_service):
    mock_playback_service.proxy_head.side_effect = PlaybackNotAllowedError("not allowed")

    response = client.request("HEAD", "/stream/jellyfin/item-denied")

    assert response.status_code == 403


def test_start_stream_uses_existing_play_session_id(client, mock_playback_service):
    response = client.post(
        "/stream/jellyfin/item-1/start",
        json={"play_session_id": "sess-existing"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "play_session_id": "sess-start",
        "item_id": "item-1",
    }
    mock_playback_service.start_playback.assert_awaited_once_with(
        "item-1",
        play_session_id="sess-existing",
        user_id="test-user-id",
    )


def test_start_stream_without_payload_uses_service_default(client, mock_playback_service):
    response = client.post("/stream/jellyfin/item-2/start")

    assert response.status_code == 200
    assert response.json()["item_id"] == "item-2"
    mock_playback_service.start_playback.assert_awaited_once_with(
        "item-2",
        play_session_id=None,
        user_id="test-user-id",
    )



from core.dependencies import get_local_files_service


@pytest.fixture
def mock_local_service():
    mock = MagicMock()
    mock.head_track = AsyncMock(
        return_value={
            "Content-Type": "audio/flac",
            "Content-Length": "30000000",
            "Accept-Ranges": "bytes",
        }
    )
    return mock


@pytest.fixture
def local_client(mock_local_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_local_files_service] = lambda: mock_local_service
    return TestClient(app)


def test_head_local_returns_200_with_headers(local_client, mock_local_service):
    response = local_client.request("HEAD", "/stream/local/42")

    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    mock_local_service.head_track.assert_awaited_once_with("42")


def test_head_local_returns_404_when_not_found(local_client, mock_local_service):
    mock_local_service.head_track.side_effect = ResourceNotFoundError("not found")

    response = local_client.request("HEAD", "/stream/local/999")

    assert response.status_code == 404


def test_head_local_returns_403_on_permission_error(local_client, mock_local_service):
    mock_local_service.head_track.side_effect = PermissionError("outside dir")

    response = local_client.request("HEAD", "/stream/local/42")

    assert response.status_code == 403

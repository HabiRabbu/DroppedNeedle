"""Per-track download route tests (Phase 7): POST /tracks/{recording_mbid}/request."""

from unittest.mock import AsyncMock

from fastapi import FastAPI

from api.v1.routes import tracks
from core.dependencies import get_download_service
from middleware import _get_current_user
from services.native.download_service import ALREADY_IN_LIBRARY
from tests.helpers import build_test_client, mock_user


def _app(service) -> FastAPI:
    app = FastAPI()
    app.include_router(tracks.router)
    app.dependency_overrides[get_download_service] = lambda: service
    app.dependency_overrides[_get_current_user] = lambda: mock_user(role="user", user_id="u1")
    return app


def test_request_track_queued():
    service = AsyncMock()
    service.request_track.return_value = "task-1"
    response = build_test_client(_app(service)).post(
        "/tracks/rec-1/request",
        json={"artist_name": "Radiohead", "track_title": "Airbag"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "queued"
    assert body["task_id"] == "task-1"
    service.request_track.assert_awaited_once()
    kwargs = service.request_track.await_args.kwargs
    assert kwargs["recording_mbid"] == "rec-1"
    assert kwargs["user_id"] == "u1"


def test_request_track_already_in_library():
    service = AsyncMock()
    service.request_track.return_value = ALREADY_IN_LIBRARY
    response = build_test_client(_app(service)).post(
        "/tracks/rec-1/request",
        json={"artist_name": "Radiohead", "track_title": "Airbag"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "already_in_library"
    assert body["task_id"] is None


def test_request_track_unauthenticated_401():
    service = AsyncMock()
    app = FastAPI()
    app.include_router(tracks.router)
    app.dependency_overrides[get_download_service] = lambda: service
    response = build_test_client(app).post(
        "/tracks/rec-1/request",
        json={"artist_name": "Radiohead", "track_title": "Airbag"},
    )
    assert response.status_code == 401

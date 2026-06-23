import time

import pytest
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.scrobble import router as scrobble_router
from api.v1.schemas.scrobble import ScrobbleResponse, ServiceResult
from core.dependencies import get_scrobble_service
from core.exceptions import ConfigurationError, ExternalServiceError
from tests.helpers import build_test_client, override_user_auth


def _success_response() -> ScrobbleResponse:
    return ScrobbleResponse(
        accepted=True,
        services={
            "lastfm": ServiceResult(success=True),
            "listenbrainz": ServiceResult(success=True),
        },
    )


def _failure_response() -> ScrobbleResponse:
    return ScrobbleResponse(
        accepted=False,
        services={
            "lastfm": ServiceResult(success=False, error="API down"),
        },
    )


@pytest.fixture
def mock_scrobble_service():
    mock = AsyncMock()
    mock.report_now_playing.return_value = _success_response()
    mock.submit_scrobble.return_value = _success_response()
    return mock


@pytest.fixture
def client(mock_scrobble_service):
    app = FastAPI()
    app.include_router(scrobble_router)
    app.dependency_overrides[get_scrobble_service] = lambda: mock_scrobble_service
    override_user_auth(app, user_id="route-user")
    return build_test_client(app)


def test_submit_requires_auth(mock_scrobble_service):
    app = FastAPI()
    app.include_router(scrobble_router)
    app.dependency_overrides[get_scrobble_service] = lambda: mock_scrobble_service
    unauth_client = build_test_client(app)
    resp = unauth_client.post(
        "/scrobble/submit",
        json={"track_name": "S", "artist_name": "A", "timestamp": int(time.time()) - 60, "duration_ms": 200000},
    )
    assert resp.status_code == 401


def test_submit_passes_current_user_id(client, mock_scrobble_service):
    resp = client.post(
        "/scrobble/submit",
        json={"track_name": "S", "artist_name": "A", "timestamp": int(time.time()) - 60, "duration_ms": 200000},
    )
    assert resp.status_code == 200
    assert mock_scrobble_service.submit_scrobble.await_args.kwargs["user_id"] == "route-user"


class TestNowPlaying:
    def test_success(self, client):
        resp = client.post(
            "/scrobble/now-playing",
            json={"track_name": "Song", "artist_name": "Artist", "album_name": "Album", "duration_ms": 200000},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True
        assert "lastfm" in data["services"]

    def test_missing_required_field(self, client):
        resp = client.post(
            "/scrobble/now-playing",
            json={"artist_name": "Artist"},
        )
        assert resp.status_code == 422

    def test_config_error_returns_400(self, client, mock_scrobble_service):
        mock_scrobble_service.report_now_playing.side_effect = ConfigurationError("No API key")
        resp = client.post(
            "/scrobble/now-playing",
            json={"track_name": "Song", "artist_name": "Artist", "album_name": "Album", "duration_ms": 200000},
        )
        assert resp.status_code == 400
        assert "not configured" in resp.json()["error"]["message"].lower()

    def test_external_error_returns_502(self, client, mock_scrobble_service):
        mock_scrobble_service.report_now_playing.side_effect = ExternalServiceError("timeout")
        resp = client.post(
            "/scrobble/now-playing",
            json={"track_name": "Song", "artist_name": "Artist", "album_name": "Album", "duration_ms": 200000},
        )
        assert resp.status_code == 502

    def test_unexpected_error_returns_500(self, client, mock_scrobble_service):
        mock_scrobble_service.report_now_playing.side_effect = RuntimeError("crash")
        resp = client.post(
            "/scrobble/now-playing",
            json={"track_name": "Song", "artist_name": "Artist", "album_name": "Album", "duration_ms": 200000},
        )
        assert resp.status_code == 500
        assert resp.json()["error"]["message"] == "Internal server error"


class TestSubmitScrobble:
    def test_success(self, client):
        ts = int(time.time()) - 60
        resp = client.post(
            "/scrobble/submit",
            json={
                "track_name": "Song",
                "artist_name": "Artist",
                "album_name": "Album",
                "timestamp": ts,
                "duration_ms": 200000,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is True

    def test_future_timestamp_rejected(self, client):
        resp = client.post(
            "/scrobble/submit",
            json={
                "track_name": "Song",
                "artist_name": "Artist",
                "album_name": "Album",
                "timestamp": int(time.time()) + 3600,
                "duration_ms": 200000,
            },
        )
        assert resp.status_code == 422

    def test_old_timestamp_rejected(self, client):
        resp = client.post(
            "/scrobble/submit",
            json={
                "track_name": "Song",
                "artist_name": "Artist",
                "album_name": "Album",
                "timestamp": int(time.time()) - 15 * 86400,
                "duration_ms": 200000,
            },
        )
        assert resp.status_code == 422

    def test_config_error_returns_400(self, client, mock_scrobble_service):
        mock_scrobble_service.submit_scrobble.side_effect = ConfigurationError("bad config")
        ts = int(time.time()) - 60
        resp = client.post(
            "/scrobble/submit",
            json={
                "track_name": "Song",
                "artist_name": "Artist",
                "album_name": "Album",
                "timestamp": ts,
                "duration_ms": 200000,
            },
        )
        assert resp.status_code == 400

    def test_external_error_returns_502(self, client, mock_scrobble_service):
        mock_scrobble_service.submit_scrobble.side_effect = ExternalServiceError("bad gateway")
        ts = int(time.time()) - 60
        resp = client.post(
            "/scrobble/submit",
            json={
                "track_name": "Song",
                "artist_name": "Artist",
                "album_name": "Album",
                "timestamp": ts,
                "duration_ms": 200000,
            },
        )
        assert resp.status_code == 502

    def test_response_includes_service_details(self, client, mock_scrobble_service):
        mock_scrobble_service.submit_scrobble.return_value = _failure_response()
        ts = int(time.time()) - 60
        resp = client.post(
            "/scrobble/submit",
            json={
                "track_name": "Song",
                "artist_name": "Artist",
                "album_name": "Album",
                "timestamp": ts,
                "duration_ms": 200000,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted"] is False
        assert data["services"]["lastfm"]["success"] is False
        assert "API down" in data["services"]["lastfm"]["error"]

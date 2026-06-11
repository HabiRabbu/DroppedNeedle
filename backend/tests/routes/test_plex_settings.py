from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ROOT_APP_DIR", tempfile.mkdtemp())

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.settings import router as settings_router
from api.v1.schemas.settings import PlexConnectionSettings
from core.dependencies import get_preferences_service, get_settings_service
from core.exceptions import ConfigurationError
from tests.helpers import override_admin_auth


@pytest.fixture
def mock_preferences():
    mock = MagicMock()
    mock.get_plex_connection.return_value = PlexConnectionSettings(
        enabled=True,
        plex_url="http://plex:32400",
        plex_token="tok-123",
        music_library_ids=["1"],
        scrobble_to_plex=True,
    )
    mock.get_plex_connection_raw.return_value = MagicMock(
        plex_url="http://plex:32400",
        plex_token="tok-123",
    )
    mock.save_plex_connection = MagicMock()
    mock.get_setting = MagicMock(return_value="client-id-123")
    return mock


@pytest.fixture
def mock_settings_service():
    mock = MagicMock()
    mock.on_plex_settings_changed = AsyncMock()

    verify_result = MagicMock()
    verify_result.valid = True
    verify_result.message = "Connected"
    verify_result.libraries = [("1", "Music")]
    mock.verify_plex = AsyncMock(return_value=verify_result)
    return mock


@pytest.fixture
def settings_client(mock_preferences, mock_settings_service):
    app = FastAPI()
    app.include_router(settings_router)
    app.dependency_overrides[get_preferences_service] = lambda: mock_preferences
    app.dependency_overrides[get_settings_service] = lambda: mock_settings_service
    override_admin_auth(app)
    return TestClient(app)


class TestGetPlexSettings:
    def test_returns_settings(self, settings_client):
        resp = settings_client.get("/settings/plex")
        assert resp.status_code == 200
        data = resp.json()
        assert data["enabled"] is True
        assert data["plex_url"] == "http://plex:32400"
        assert data["music_library_ids"] == ["1"]


class TestUpdatePlexSettings:
    def test_saves_and_returns(self, settings_client, mock_preferences, mock_settings_service):
        payload = {
            "enabled": True,
            "plex_url": "http://plex:32400",
            "plex_token": "new-tok",
            "music_library_ids": ["1", "2"],
            "scrobble_to_plex": False,
        }
        resp = settings_client.put("/settings/plex", json=payload)
        assert resp.status_code == 200
        mock_preferences.save_plex_connection.assert_called_once()
        mock_settings_service.on_plex_settings_changed.assert_awaited_once()

    def test_400_on_config_error(self, settings_client, mock_preferences):
        mock_preferences.save_plex_connection.side_effect = ConfigurationError("bad")
        payload = {
            "enabled": True,
            "plex_url": "",
            "plex_token": "",
        }
        resp = settings_client.put("/settings/plex", json=payload)
        assert resp.status_code == 400


class TestVerifyPlexConnection:
    def test_verify_success(self, settings_client):
        payload = {
            "enabled": True,
            "plex_url": "http://plex:32400",
            "plex_token": "tok",
        }
        resp = settings_client.post("/settings/plex/verify", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["valid"] is True
        assert len(data["libraries"]) == 1
        assert data["libraries"][0]["key"] == "1"

    def test_verify_invalid(self, settings_client, mock_settings_service):
        result = MagicMock()
        result.valid = False
        result.message = "Connection refused"
        result.libraries = []
        mock_settings_service.verify_plex = AsyncMock(return_value=result)

        payload = {
            "enabled": True,
            "plex_url": "http://bad:32400",
            "plex_token": "tok",
        }
        resp = settings_client.post("/settings/plex/verify", json=payload)
        assert resp.status_code == 200
        assert resp.json()["valid"] is False


class TestGetPlexLibraries:
    def test_returns_libraries(self, settings_client, mock_settings_service):
        mock_settings_service.get_plex_libraries = AsyncMock(return_value=[("1", "Music")])

        resp = settings_client.get("/settings/plex/libraries")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Music"

    def test_400_when_not_configured(self, settings_client, mock_settings_service):
        mock_settings_service.get_plex_libraries = AsyncMock(
            side_effect=ValueError("Plex is not configured")
        )

        resp = settings_client.get("/settings/plex/libraries")
        assert resp.status_code == 400

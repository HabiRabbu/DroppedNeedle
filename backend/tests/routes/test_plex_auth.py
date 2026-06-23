from __future__ import annotations

import os
import tempfile

os.environ.setdefault("ROOT_APP_DIR", tempfile.mkdtemp())

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.plex_auth import router as auth_router
from api.v1.schemas.settings import PlexOAuthPinResponse, PlexOAuthPollResponse
from core.dependencies import get_plex_repository, get_preferences_service
from core.exceptions import PlexApiError


@pytest.fixture
def mock_preferences():
    mock = MagicMock()
    mock.get_setting = MagicMock(return_value="existing-client-id")
    mock.save_setting = MagicMock()
    mock.get_or_create_setting = MagicMock(return_value="existing-client-id")
    return mock


@pytest.fixture
def mock_repo():
    mock = MagicMock()
    pin = MagicMock()
    pin.id = 12345
    pin.code = "ABCD"
    mock.create_oauth_pin = AsyncMock(return_value=pin)
    mock.poll_oauth_pin = AsyncMock(return_value=None)
    return mock


@pytest.fixture
def auth_client(mock_preferences, mock_repo):
    app = FastAPI()
    app.include_router(auth_router)
    app.dependency_overrides[get_preferences_service] = lambda: mock_preferences
    app.dependency_overrides[get_plex_repository] = lambda: mock_repo
    return TestClient(app)


class TestCreatePlexPin:
    def test_creates_pin(self, auth_client):
        resp = auth_client.post("/plex/auth/pin")
        assert resp.status_code == 200
        data = resp.json()
        assert data["pin_id"] == 12345
        assert data["pin_code"] == "ABCD"
        assert "auth_url" in data
        assert "clientID=existing-client-id" in data["auth_url"]

    def test_generates_client_id_if_missing(self, auth_client, mock_preferences):
        import uuid
        generated = str(uuid.uuid4())
        mock_preferences.get_or_create_setting = MagicMock(return_value=generated)
        resp = auth_client.post("/plex/auth/pin")
        assert resp.status_code == 200
        mock_preferences.get_or_create_setting.assert_called_once()
        call_args = mock_preferences.get_or_create_setting.call_args
        assert call_args[0][0] == "plex_client_id"

    def test_502_on_plex_error(self, auth_client, mock_repo):
        mock_repo.create_oauth_pin = AsyncMock(side_effect=PlexApiError("timeout"))
        resp = auth_client.post("/plex/auth/pin")
        assert resp.status_code == 502

    def test_500_on_unexpected_error(self, auth_client, mock_repo):
        mock_repo.create_oauth_pin = AsyncMock(side_effect=RuntimeError("bad"))
        resp = auth_client.post("/plex/auth/pin")
        assert resp.status_code == 500


class TestGetOrCreateSettingNoDeadlock:
    def test_get_or_create_setting_does_not_deadlock(self, tmp_path):
        import threading

        from core.config import Settings
        from services.preferences_service import PreferencesService

        config_path = tmp_path / "config.json"
        settings = Settings(
            root_app_dir=tmp_path,
            config_file_path=config_path,
            cache_dir=tmp_path / "cache",
            library_db_path=tmp_path / "cache" / "library.db",
        )

        result = None
        exc = None

        def run():
            nonlocal result, exc
            try:
                prefs = PreferencesService(settings)
                result = prefs.get_or_create_setting("plex_client_id", lambda: "test-client-id")
                result = (result, prefs.get_or_create_setting("plex_client_id", lambda: "other"))
            except (OSError, ValueError, RuntimeError) as e:
                exc = e

        t = threading.Thread(target=run)
        t.start()
        t.join(timeout=5)
        assert not t.is_alive(), "Deadlock detected: PreferencesService hung for 5s"
        assert exc is None
        assert result[0] == "test-client-id"
        assert result[1] == "test-client-id"


class TestPollPlexPin:
    def test_poll_pending(self, auth_client):
        resp = auth_client.get("/plex/auth/poll?pin_id=12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed"] is False
        assert data["auth_token"] == ""

    def test_poll_completed(self, auth_client, mock_repo):
        mock_repo.poll_oauth_pin = AsyncMock(return_value="auth-token-abc")
        resp = auth_client.get("/plex/auth/poll?pin_id=12345")
        assert resp.status_code == 200
        data = resp.json()
        assert data["completed"] is True
        assert data["auth_token"] == "auth-token-abc"

    def test_poll_502_on_error(self, auth_client, mock_repo):
        mock_repo.poll_oauth_pin = AsyncMock(side_effect=Exception("network error"))
        resp = auth_client.get("/plex/auth/poll?pin_id=12345")
        assert resp.status_code == 502

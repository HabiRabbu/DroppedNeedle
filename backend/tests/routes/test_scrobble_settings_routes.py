import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.routes.settings import router
from api.v1.schemas.settings import ScrobbleSettings
from core.dependencies import get_preferences_service
from core.exceptions import ConfigurationError
from tests.helpers import build_test_client, override_admin_auth


def _default_scrobble_settings() -> ScrobbleSettings:
    return ScrobbleSettings(scrobble_to_lastfm=True, scrobble_to_listenbrainz=False)


@pytest.fixture
def mock_prefs():
    mock = MagicMock()
    mock.get_scrobble_settings.return_value = _default_scrobble_settings()
    mock.save_scrobble_settings = MagicMock()
    return mock


@pytest.fixture
def client(mock_prefs):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_preferences_service] = lambda: mock_prefs
    override_admin_auth(app)
    yield build_test_client(app)


class TestGetScrobbleSettings:
    def test_returns_settings(self, client):
        resp = client.get("/settings/scrobble")
        assert resp.status_code == 200
        data = resp.json()
        assert data["scrobble_to_lastfm"] is True
        assert data["scrobble_to_listenbrainz"] is False

    def test_server_error(self, client, mock_prefs):
        mock_prefs.get_scrobble_settings.side_effect = RuntimeError("boom")
        resp = client.get("/settings/scrobble")
        assert resp.status_code == 500
        assert resp.json()["error"]["message"] == "Internal server error"


class TestUpdateScrobbleSettings:
    def test_saves_and_returns(self, client, mock_prefs):
        updated = ScrobbleSettings(scrobble_to_lastfm=False, scrobble_to_listenbrainz=True)
        mock_prefs.get_scrobble_settings.return_value = updated
        resp = client.put(
            "/settings/scrobble",
            json={"scrobble_to_lastfm": False, "scrobble_to_listenbrainz": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["scrobble_to_lastfm"] is False
        assert data["scrobble_to_listenbrainz"] is True
        mock_prefs.save_scrobble_settings.assert_called_once()

    def test_config_error_returns_400(self, client, mock_prefs):
        mock_prefs.save_scrobble_settings.side_effect = ConfigurationError("bad")
        resp = client.put(
            "/settings/scrobble",
            json={"scrobble_to_lastfm": True, "scrobble_to_listenbrainz": True},
        )
        assert resp.status_code == 400

    def test_server_error_returns_500(self, client, mock_prefs):
        mock_prefs.save_scrobble_settings.side_effect = RuntimeError("disk full")
        resp = client.put(
            "/settings/scrobble",
            json={"scrobble_to_lastfm": True, "scrobble_to_listenbrainz": True},
        )
        assert resp.status_code == 500
        assert resp.json()["error"]["message"] == "Internal server error"

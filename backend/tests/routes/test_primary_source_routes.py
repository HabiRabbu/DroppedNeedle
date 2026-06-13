import pytest
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from api.v1.schemas.settings import PrimaryMusicSourceSettings
from api.v1.routes.settings import router
from core.dependencies import get_preferences_service, get_settings_service
from tests.helpers import override_admin_auth


@pytest.fixture
def mock_prefs():
    mock = MagicMock()
    mock.get_primary_music_source.return_value = PrimaryMusicSourceSettings(source="listenbrainz")
    mock.save_primary_music_source = MagicMock()
    return mock


@pytest.fixture
def mock_settings_service():
    mock = MagicMock()
    mock.clear_home_cache = AsyncMock(return_value=5)
    mock.clear_source_resolution_cache = AsyncMock(return_value=3)
    return mock


@pytest.fixture
def client(mock_prefs, mock_settings_service):
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_preferences_service] = lambda: mock_prefs
    app.dependency_overrides[get_settings_service] = lambda: mock_settings_service
    override_admin_auth(app)
    yield TestClient(app)


class TestGetPrimarySource:
    def test_returns_current_source(self, client, mock_prefs):
        resp = client.get("/settings/primary-source")
        assert resp.status_code == 200
        assert resp.json()["source"] == "listenbrainz"

    def test_returns_lastfm_when_configured(self, client, mock_prefs):
        mock_prefs.get_primary_music_source.return_value = PrimaryMusicSourceSettings(
            source="lastfm"
        )
        resp = client.get("/settings/primary-source")
        assert resp.status_code == 200
        assert resp.json()["source"] == "lastfm"


class TestUpdatePrimarySource:
    def test_updates_to_lastfm(self, client, mock_prefs):
        mock_prefs.get_primary_music_source.return_value = PrimaryMusicSourceSettings(
            source="lastfm"
        )
        resp = client.put(
            "/settings/primary-source",
            json={"source": "lastfm"},
        )
        assert resp.status_code == 200
        assert resp.json()["source"] == "lastfm"
        mock_prefs.save_primary_music_source.assert_called_once()

    def test_updates_to_listenbrainz(self, client, mock_prefs):
        resp = client.put(
            "/settings/primary-source",
            json={"source": "listenbrainz"},
        )
        assert resp.status_code == 200
        mock_prefs.save_primary_music_source.assert_called_once()

    def test_rejects_invalid_source(self, client, mock_prefs):
        resp = client.put(
            "/settings/primary-source",
            json={"source": "invalid"},
        )
        assert resp.status_code == 422
        mock_prefs.save_primary_music_source.assert_not_called()

    def test_clears_cache_on_update(self, client, mock_prefs, mock_settings_service):
        resp = client.put(
            "/settings/primary-source",
            json={"source": "lastfm"},
        )
        assert resp.status_code == 200
        mock_settings_service.clear_home_cache.assert_awaited_once()
        mock_settings_service.clear_source_resolution_cache.assert_awaited_once()
